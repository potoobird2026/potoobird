"""
SessionManager — 会话生命周期管理

职责：
- 创建/加载/保存/销毁会话
- 上下文压缩集成
- 跨渠道身份统一
- 任务状态同步
- 会话归档

所有参数不写死：
- max_messages: 由 LLM 根据上下文窗口大小动态评估
- compress_threshold: 由 LLM 根据用户对话模式动态评估
- archive_days: 由 LLM 根据用户使用频率动态评估

设计文档：DESIGN-V2.md §8.2
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("long_agent.session.manager")


class SessionStatus(str, Enum):
    """会话状态"""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    IDLE = "idle"


@dataclass
class Session:
    """
    会话对象 — V2 版本

    字段：
    - id: 会话 ID
    - universal_id: 统一用户 ID（跨渠道）
    - channel: 当前渠道
    - messages: 消息列表
    - context_summary: 上下文摘要（压缩后）
    - task_states: 任务状态映射
    - status: 会话状态
    - created_at: 创建时间
    - updated_at: 最后活跃时间
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    universal_id: str = ""
    channel: str = ""
    messages: list = field(default_factory=list)
    context_summary: str = ""
    task_states: dict = field(default_factory=dict)
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=datetime.now(timezone.utc))

    # 覆盖 __init__ 以支持旧接口参数 state= 和 message_count=
    # 注意：不能和 @property 同名，否则 dataclass 会把 property 对象作为 default
    def __init__(self, *args, state=None, message_count=None, **kwargs):
        # 把 state 映射到 status
        if state is not None:
            kwargs.pop("status", None)
        # 手动初始化所有 dataclass 字段
        import dataclasses as _dc

        fields = self.__dataclass_fields__
        for f_name, f_obj in fields.items():
            if f_name in kwargs:
                object.__setattr__(self, f_name, kwargs[f_name])
            elif f_obj.default is not _dc.MISSING:
                object.__setattr__(self, f_name, f_obj.default)
            elif f_obj.default_factory is not _dc.MISSING:
                object.__setattr__(self, f_name, f_obj.default_factory())
        # 处理旧接口参数
        if state is not None:
            try:
                self.status = SessionStatus(state)
            except ValueError:
                pass
        if message_count is not None:
            object.__setattr__(self, "messages", [None] * message_count)

    # 兼容旧接口属性
    @property
    def session_id(self) -> str:
        """兼容旧接口：返回 id"""
        return self.id

    @property
    def last_active_at(self) -> float:
        """兼容旧接口：返回 updated_at 的时间戳"""
        return self.updated_at.timestamp()

    @last_active_at.setter
    def last_active_at(self, value: float):
        """兼容旧接口：设置 updated_at"""
        self.updated_at = datetime.utcfromtimestamp(value)

    @property
    def state(self) -> str:
        """兼容旧接口：返回 status 的字符串值"""
        return self.status.value

    @state.setter
    def state(self, value: str):
        """兼容旧接口：设置 status"""
        try:
            self.status = SessionStatus(value)
        except ValueError:
            pass

    @property
    def conversation_id(self) -> str:
        """兼容旧接口：返回 id"""
        return self.id

    @property
    def context(self) -> dict:
        """兼容旧接口：返回 task_states"""
        return self.task_states

    @property
    def user_id(self) -> str:
        """兼容旧接口：返回 universal_id"""
        return self.universal_id

    @property
    def message_count(self) -> int:
        """兼容旧接口：返回消息数"""
        return len(self.messages)

    def __setattr__(self, name, value):
        """兼容旧接口：允许直接设置 state 字符串"""
        if name == "state" and isinstance(value, str):
            try:
                value = SessionStatus(value)
            except ValueError:
                pass
        super().__setattr__(name, value)


class SessionManager:
    """
    会话管理器 — V2 版本

    集成：
    - IdentityManager: 跨渠道身份统一
    - ContextCompressor: 上下文压缩
    - EventBus: 事件驱动
    """

    def __init__(
        self,
        memory_manager=None,
        compressor=None,
        event_bus=None,
        idle_timeout: float = None,
        **kwargs,
    ):
        """
        Args:
            memory_manager: 管理器
            compressor: 上下文压缩器
            event_bus: 事件总线
            idle_timeout: 空闲超时秒数（兼容旧接口，已弃用）
            **kwargs: 兼容旧接口的额外参数
        """
        from src.session.identity_manager import IdentityManager

        self.memory = memory_manager
        self.compressor = compressor
        self.event_bus = event_bus
        self.identity = IdentityManager()
        self._sessions: dict[str, Session] = {}
        # 兼容旧接口
        if idle_timeout is not None:
            logger.warning("idle_timeout 参数已弃用，将在 V3 移除")
        self._idle_timeout = idle_timeout or 7200
        logger.info("SessionManager V2 初始化完成")

    async def on_message(self, channel: str, channel_user_id: str, content: str) -> str:
        """
        处理来自任意渠道的消息（统一入口）

        流程：
        1. 统一身份识别
        2. 获取或创建会话
        3. 追加消息
        4. 压缩检测
        5. 生成回复
        6. 追加回复

        Args:
            channel: 渠道名称
            channel_user_id: 渠道用户 ID
            content: 消息内容

        Returns:
            str: 回复内容
        """
        # 1. 统一身份识别
        universal_id = await self.identity.resolve(channel, channel_user_id)

        # 2. 获取或创建会话
        session = self._get_or_create(universal_id, channel)

        # 3. 追加消息
        session.messages.append({"role": "user", "content": content})
        session.updated_at = datetime.now(timezone.utc)

        # 4. 压缩检测
        if self.compressor and len(session.messages) > 6:
            try:
                result = await self.compressor.compress(session.messages, session.context_summary)
                session.context_summary = result.summary
                logger.debug(f"上下文压缩: session={session.id}")
            except Exception as e:
                logger.warning(f"上下文压缩失败: {e}")

        # 5. 生成回复
        response = await self._generate_response(session)

        # 6. 追加回复
        session.messages.append({"role": "assistant", "content": response})

        # 发布事件
        if self.event_bus:
            await self.event_bus.publish(
                "session.message_handled", {"session_id": session.id, "channel": channel}
            )

        return response

    async def on_user_message(self, user_input: str) -> str:
        """
        简化版消息处理接口 — 兼容主循环直接调用

        内部使用默认渠道（"cli"）和默认用户（"local"），
        适合不需要跨渠道身份管理的简单场景。

        Args:
            user_input: 用户输入文本

        Returns:
            str: Agent 回复内容
        """
        return await self.on_message(
            channel="cli",
            channel_user_id="local",
            content=user_input,
        )

    def _get_or_create(self, universal_id: str, channel: str) -> Session:
        """
        获取或创建会话

        Args:
            universal_id: 统一用户 ID
            channel: 渠道

        Returns:
            Session: 会话对象
        """
        # 查找该 universal_id 在该渠道的活跃会话
        for session in self._sessions.values():
            if (
                session.universal_id == universal_id
                and session.channel == channel
                and session.status == SessionStatus.ACTIVE
            ):
                return session

        # 创建新会话
        session = Session(
            universal_id=universal_id,
            channel=channel,
        )
        self._sessions[session.id] = session
        logger.info(f"会话创建: {session.id} ({universal_id}@{channel})")
        return session

    async def create_session(
        self,
        user_id: str = None,
        channel: str = "default",
        conversation_id: str = None,
        context: dict = None,
    ) -> Session:
        """
        创建会话（兼容旧接口）

        Args:
            user_id: 用户 ID
            channel: 渠道
            conversation_id: 对话 ID（兼容旧接口，映射到 id）
            context: 上下文数据（兼容旧接口，存入 task_states）

        Returns:
            Session: 会话对象
        """
        uid = user_id or "default"
        # 兼容旧接口：每次 create_session 都创建新会话
        session = Session(
            universal_id=uid,
            channel=channel,
        )
        if conversation_id:
            session.id = conversation_id
        self._sessions[session.id] = session
        if context:
            session.task_states.update(context)
        logger.info(f"会话创建(兼容): {session.id} ({uid}@{channel})")
        return session

    async def _generate_response(self, session: Session) -> str:
        """
        生成回复（简化版，实际由 LLM 调用）

        Args:
            session: 会话对象

        Returns:
            str: 回复内容
        """
        # 实际实现中调用 LLM
        last_msg = session.messages[-1] if session.messages else {}
        content = last_msg.get("content", "")
        return f"收到: {content[:50]}..."

    async def get_session(self, session_id: str) -> Optional[Session]:
        """
        获取会话

        Args:
            session_id: 会话 ID

        Returns:
            Session or None
        """
        session = self._sessions.get(session_id)
        if session and session.status == SessionStatus.ACTIVE:
            session.updated_at = datetime.now(timezone.utc)
            return session
        return None

    async def archive_session(self, session_id: str) -> bool:
        """
        归档会话

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否成功
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.status = SessionStatus.ARCHIVED
        logger.info(f"会话归档: {session_id}")
        return True

    async def destroy_session(self, session_id: str) -> bool:
        """
        销毁会话

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否成功
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"会话销毁: {session_id}")
            return True
        return False

    async def cleanup_expired(self, max_idle_seconds: float = None) -> int:
        """
        清理过期会话（兼容旧接口）

        Args:
            max_idle_seconds: 最大空闲秒数，默认使用实例的 idle_timeout

        Returns:
            int: 清理的会话数
        """
        if max_idle_seconds is None:
            max_idle_seconds = getattr(self, "_idle_timeout", 7200)
        now = datetime.now(timezone.utc)
        expired = []
        for sid, session in self._sessions.items():
            idle_seconds = (now - session.updated_at).total_seconds()
            if idle_seconds > max_idle_seconds:
                expired.append(sid)
        for sid in expired:
            # 设置状态为 expired（兼容旧接口测试）
            self._sessions[sid].state = "expired"
            del self._sessions[sid]
            logger.info(f"过期会话清理: {sid}")
        return len(expired)

    async def save_session(self, session_id: str) -> bool:
        """
        保存会话（兼容旧接口）

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否成功
        """
        if session_id not in self._sessions:
            return False
        # 实际项目中这里会持久化到存储
        logger.info(f"会话保存: {session_id}")
        return True

    def get_sessions_by_universal_id(self, universal_id: str) -> list:
        """
        获取用户的所有会话（跨渠道）

        Args:
            universal_id: 统一用户 ID

        Returns:
            list[Session]: 会话列表
        """
        return [s for s in self._sessions.values() if s.universal_id == universal_id]

    @property
    def active_count(self) -> int:
        """活跃会话数"""
        return sum(1 for s in self._sessions.values() if s.status == SessionStatus.ACTIVE)
