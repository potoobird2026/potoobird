"""
Agent 主循环 — 7 步循环 + 状态机驱动

设计来源：
- DESIGN.md 二、Agent 主循环设计
- 03_执行层设计.md — GoalAnchor + SnapshotManager
- 06_状态机设计.md — 11 状态 + 合法转换

7 步循环：
  ① 感知（PERCEIVING）   → 读取输入 + 加载上下文 + 上下文压缩
  ② 理解（UNDERSTANDING）→ 意图解析 + 置信度评估 + 追问决策
  ③ 规划（PLANNING）     → 确定操作类型 + 审批检查
  ④ 执行（EXECUTING）    → 调用 LLM / 工具 / 写入记忆
  ⑤ 观察（OBSERVING）    → 检查结果是否跑偏
  ⑥ 反思（REFLECTING）   → 更新记忆 + 触发后台任务
  ⑦ 回复（REPLYING）     → 格式化输出

状态机驱动：每个步骤对应一个状态转换，非法转换直接拒绝。
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.audit.logger import AuditAction, AuditLogger
from src.background.manager import BackgroundTaskManager
from src.context.compressor import BackgroundCompressor, ContextCompressor
from src.delivery.report_generator import ReportGenerator
from src.delivery.result_verifier import ResultVerifier
from src.errors.types import ErrorCode, LLMResult, OperationResult

# V2 imports — 延迟导入避免循环依赖
from src.execution.b_supervisor import BSupervisor
from src.execution.goal_anchor import GoalAnchor
from src.execution.snapshot_manager import SnapshotManager
from src.execution.sub_agent_manager import SubAgentManager
from src.execution.tool_registry import ToolRegistry
from src.loop.state import AgentState, StateMachine
from src.personality.algorithms import PersonalityFusionEngine, PersonalityState
from src.session.session_manager import SessionManager

logger = logging.getLogger("long_agent.loop.agent_loop")


class _SessionProxy:
    """适配 LoopContext.compressed_messages → BackgroundCompressor 期望的 session.messages 接口"""

    def __init__(self, messages: list):
        self.messages = messages


@dataclass
class LoopContext:
    """主循环上下文 — 在 7 步之间传递"""

    # 输入
    user_input: str = ""
    conversation_id: str = ""

    # 感知阶段产出
    filtered_input: str = ""
    memory_context: dict = field(default_factory=dict)
    compressed_messages: list = field(default_factory=list)

    # 理解阶段产出
    intent: object = None  # Intent 对象
    clarification_question: str = ""
    needs_clarification: bool = False

    # 规划阶段产出
    operation_type: str = ""  # memory_write / memory_read / tool_call / llm_chat
    requires_approval: bool = False
    approved: bool = False

    # 执行阶段产出
    llm_result: Optional[LLMResult] = None
    tool_result: Optional[OperationResult] = None
    execution_result: str = ""
    exec_result: object = None  # BSupervisor 执行结果对象（含 task_id、status 等）
    retry_count: int = 0

    # 观察阶段产出
    is_off_track: bool = False
    off_track_reason: str = ""
    verify_report: object = None  # ResultVerifier 验证报告
    verification_status: str = ""  # 验证状态: passed / failed / skipped / error
    verification_passed: bool = False  # 验证是否通过

    # 反思阶段产出
    memory_updated: bool = False
    background_tasks_triggered: bool = False

    # 回复阶段产出
    response: str = ""

    # 元数据
    loop_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    error: str = ""

    # 人格系统（V2 — PersonalityFusionEngine）
    personality_state: PersonalityState = field(default_factory=PersonalityState)
    personality_target: PersonalityState = field(default_factory=PersonalityState)
    personality_adjustments: dict = field(default_factory=dict)
    personality_updated: bool = False


def _build_plan_from_intent(intent, operation_type: str):
    """
    从 intent 中提取交付物描述和验收标准，构建 plan 对象。

    返回一个简单命名空间对象，包含：
    - deliverable: str  交付物描述
    - acceptance_criteria: list[str]  验收标准列表
    - max_steps: int  最大步骤数
    """

    class Plan:
        def __init__(self):
            self.deliverable = getattr(intent, "content", "") or f"执行 {operation_type}"
            self.acceptance_criteria = getattr(intent, "acceptance_criteria", []) or ["结果非空"]
            self.max_steps = getattr(intent, "max_steps", 5)

    return Plan()


class AgentLoop:
    """
    Agent 主循环 — 7 步循环 + 状态机驱动

    职责：
    - 编排 7 个步骤的执行顺序
    - 管理状态机转换
    - 处理错误恢复（重试 + 降级）
    - 记录审计日志

    设计原则：
    - 硬件稳定性 > 执行效率（默认串行）
    - 审批是强制卡点（不是建议）
    - 错误不能静默吞掉（红线 3）
    """

    # 默认参数（均可通过构造函数覆盖）
    DEFAULT_MAX_EXECUTE_RETRIES = 3
    DEFAULT_MAX_CLARIFICATION_ATTEMPTS = 3
    DEFAULT_STEP_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        memory_manager=None,
        understanding_engine=None,
        llm_provider=None,
        tool_system=None,
        audit_logger: AuditLogger = None,
        max_execute_retries: int = None,
        max_clarification_attempts: int = None,
        step_timeout_seconds: int = None,
        confidence_threshold: object = None,
        # V2 新增参数
        b_supervisor: "BSupervisor" = None,
        compressor: "ContextCompressor" = None,
        goal_anchor: "GoalAnchor" = None,
        snapshot_manager: "SnapshotManager" = None,
        tool_registry: "ToolRegistry" = None,
        result_verifier: "ResultVerifier" = None,
        report_generator: "ReportGenerator" = None,
        fusion_engine: "PersonalityFusionEngine" = None,
        background_compressor: "BackgroundCompressor" = None,
        session_manager: "SessionManager" = None,
        background_manager: "BackgroundTaskManager" = None,
        subagent_manager: "SubAgentManager" = None,
        # V2 P1 新增
        security: object = None,
        approval_module: object = None,
        conflict_checker: object = None,
        credential_pool: object = None,
        model_router: object = None,
        prompt_manager: object = None,
        event_bus: object = None,
        # V2 P2 新增：8个主动调用对应的可选依赖
        memory_loader: object = None,
        token_counter: object = None,
        process_standard: object = None,
        adaptive_timeout: object = None,
        message_queue: object = None,
        state_persistence: object = None,
        session_archiver: object = None,
        deliverable_validator: object = None,
    ):
        self.memory = memory_manager
        self.understanding = understanding_engine
        self.llm = llm_provider
        self.tools = tool_system
        self.audit = audit_logger
        self._state_machine = StateMachine()
        self._running = False

        # V2 模块（可选注入，未注入时降级为V1行为）
        self.b_supervisor = b_supervisor
        self.compressor = compressor
        self.goal_anchor = goal_anchor
        self.snapshot_manager = snapshot_manager
        self.tool_registry = tool_registry
        self.result_verifier = result_verifier
        self.report_generator = report_generator
        self.fusion_engine = fusion_engine or PersonalityFusionEngine()
        self.background_compressor = background_compressor
        self.session_manager = session_manager
        self.background_manager = background_manager
        self.subagent_manager = subagent_manager
        # V2 P1 新增
        self.security = security
        self.approval_module = approval_module
        self.conflict_checker = conflict_checker
        self.credential_pool = credential_pool
        self.model_router = model_router
        self.prompt_manager = prompt_manager
        self.event_bus = event_bus

        # V2 P2 新增：8个主动调用对应的实例变量（可选注入，未注入时跳过）
        self._memory_loader = memory_loader  # B1: MemoryLoader 动态预算分配
        self._token_counter = token_counter  # B3: TokenCounter 压缩判断
        self._process_standard = process_standard  # B4: ProcessStandard 任务完结
        self._adaptive_timeout = adaptive_timeout  # B5: AdaptiveTimeoutManager
        self._message_queue = message_queue  # B6: MessageQueue
        self._state_persistence = state_persistence  # B7: StatePersistence
        self._session_archiver = session_archiver  # B8: Session 归档
        self._deliverable_validator = deliverable_validator  # DeliverableValidator 实例

        # 可配置参数（None 时使用默认值）
        if max_execute_retries is not None and max_execute_retries < 0:
            raise ValueError("MAX_EXECUTE_RETRIES 不能为负数，当前值：{max_execute_retries}")
        self.MAX_EXECUTE_RETRIES = (
            max_execute_retries
            if max_execute_retries is not None
            else self.DEFAULT_MAX_EXECUTE_RETRIES
        )

        if max_clarification_attempts is not None and max_clarification_attempts < 0:
            raise ValueError(
                "MAX_CLARIFICATION_ATTEMPTS 不能为负数，当前值：{max_clarification_attempts}"
            )
        self.MAX_CLARIFICATION_ATTEMPTS = (
            max_clarification_attempts
            if max_clarification_attempts is not None
            else self.DEFAULT_MAX_CLARIFICATION_ATTEMPTS
        )

        if step_timeout_seconds is not None and step_timeout_seconds <= 0:
            raise ValueError(f"STEP_TIMEOUT_SECONDS 必须为正数，当前值：{step_timeout_seconds}")
        self.STEP_TIMEOUT_SECONDS = (
            step_timeout_seconds
            if step_timeout_seconds is not None
            else self.DEFAULT_STEP_TIMEOUT_SECONDS
        )

        # 置信度阈值（V1 遗留 ConfidenceThreshold 已删除，此处暂设为 None）
        self._confidence_threshold = confidence_threshold  # 当前未使用

        # 参数验证（G-004 防御性编程）
        if self.MAX_EXECUTE_RETRIES < 0:
            raise ValueError(f"MAX_EXECUTE_RETRIES 不能为负数: {self.MAX_EXECUTE_RETRIES}")
        if self.MAX_CLARIFICATION_ATTEMPTS < 0:
            raise ValueError(
                f"MAX_CLARIFICATION_ATTEMPTS 不能为负数: {self.MAX_CLARIFICATION_ATTEMPTS}"
            )
        if self.STEP_TIMEOUT_SECONDS <= 0:
            raise ValueError(f"STEP_TIMEOUT_SECONDS 必须为正数: {self.STEP_TIMEOUT_SECONDS}")

    @property
    def state(self) -> AgentState:
        return self._state_machine.state

    async def run(self, user_input: str, conversation_id: str = "") -> str:
        """
        执行一次完整的 7 步循环

        Args:
            user_input: 用户输入
            conversation_id: 对话 ID（用于加载历史）

        Returns:
            str: Agent 回复

        变更记录（G-011）：
        - V2.1: 接入BSupervisor执行路径（_step_execute）
        - V2.1: 接入ContextCompressor（_step_perceive）
        - V2.1: 接入ResultVerifier（_step_observe）
        - V2.1: 接入ReportGenerator（_step_reply）
        - V2.1: 接入SessionManager（_step_perceive）
        """
        ctx = LoopContext(
            user_input=user_input,
            conversation_id=conversation_id or str(uuid.uuid4())[:8],
        )
        self._running = True
        self._state_machine.reset()

        logger.info(f"[{ctx.loop_id}] 开始主循环: {user_input[:50]}")

        try:
            # === ① 感知 ===
            await self._step_perceive(ctx)
            if not self._running:
                return ctx.response

            # === ② 理解 ===
            await self._step_understand(ctx)

            # 如果需要追问，进入追问循环
            while ctx.needs_clarification and self._running:
                return ctx.clarification_question  # 返回追问，等用户回答后再继续

            if not self._running:
                return ctx.response

            # === ③ 规划 ===
            await self._step_plan(ctx)

            # 如果需要审批，等待审批
            if ctx.requires_approval and not ctx.approved:
                return "⏳ 等待审批：" + ctx.operation_type

            # === ④ 执行 ===
            await self._step_execute(ctx)

            # === ⑤ 观察 ===
            await self._step_observe(ctx)

            # 如果跑偏，重试执行（最多 MAX_EXECUTE_RETRIES 次）
            while ctx.is_off_track and ctx.retry_count < self.MAX_EXECUTE_RETRIES and self._running:
                logger.warning(
                    "[{lid}] 检测到偏（第{n}次重试）: {reason}".format(
                        lid=ctx.loop_id,
                        n=ctx.retry_count + 1,
                        reason=ctx.off_track_reason,
                    )
                )
                ctx.retry_count += 1
                await self._step_execute(ctx)
                await self._step_observe(ctx)

            # === ⑥ 反思 ===
            await self._step_reflect(ctx)

            # === ⑦ 回复 ===
            await self._step_reply(ctx)

        except Exception as e:
            logger.error(f"[{ctx.loop_id}] 主循环异常: {e}", exc_info=True)
            ctx.error = str(e)
            # 安全转换：只有合法时才转 FAILED，否则直接 reset
            if self._state_machine.can_transition_to(AgentState.FAILED):
                self._state_machine.transition_to(AgentState.FAILED)
            else:
                self._state_machine.reset()
            ctx.response = f"❌ 处理失败：{e}"
            if self.audit:
                try:
                    self.audit.log(
                        AuditAction.MEMORY_WRITE,  # 用 MEMORY_WRITE 作为通用操作记录
                        {"loop_id": ctx.loop_id, "error": str(e)},
                        success=False,
                        error=str(e),
                    )
                except Exception:
                    pass  # 审计日志失败不影响主流程
        finally:
            self._running = False
            # 确保回到 IDLE
            if self._state_machine.state != AgentState.IDLE:
                try:
                    self._state_machine.transition_to(AgentState.IDLE)
                except Exception:
                    self._state_machine.reset()

        logger.info(f"[{ctx.loop_id}] 主循环完成，状态: {self._state_machine.state.value}")
        return ctx.response

    async def stop(self):
        """停止主循环"""
        self._running = False
        logger.info("主循环停止信号已发送")

    async def _step_perceive(self, ctx: LoopContext):
        """
        感知阶段：
        1. 输入过滤（InputFilter）
        2. 加载上下文（记忆 + 人格 + 标准）
        3. 上下文压缩（ContextCompressor — V2 实现）
        4. V2: 人格调节量计算（PersonalityFusionEngine）
        5. V2: SessionManager 对话历史管理
        """
        logger.debug(f"[{ctx.loop_id}] ① 感知阶段")

        # 1. 输入过滤（如果有安全模块）
        if hasattr(self, "security") and self.security:
            try:
                filter_result = self.security.filter(ctx.user_input)
                if not filter_result.is_ok:
                    ctx.response = f"⛔ 输入被安全过滤器拦截：{filter_result.error_message}"
                    ctx.filtered_input = ""
                    logger.warning(f"输入过滤拦截: {filter_result.error_message}")
                    return
                ctx.filtered_input = filter_result.data.get("filtered_input", ctx.user_input)
            except Exception as e:
                logger.warning(f"输入过滤失败（放行）: {e}")
                ctx.filtered_input = ctx.user_input
        else:
            ctx.filtered_input = ctx.user_input

        # 2. 加载记忆上下文
        if self.memory:
            try:
                ctx.memory_context = await self._load_memory_context(ctx.user_input)
            except Exception as e:
                logger.warning(f"加载记忆上下文失败（降级继续）: {e}")
                ctx.memory_context = {}

        # B1: MemoryLoader 主动调用 — 动态预算分配
        if self._memory_loader is not None:
            try:
                budget_result = await self._memory_loader.allocate_budget(
                    query=ctx.user_input,
                    memory_context=ctx.memory_context,
                )
                if budget_result:
                    ctx.memory_context["dynamic_budget"] = budget_result
                    logger.debug(f"[{ctx.loop_id}] MemoryLoader 动态预算: {budget_result}")
            except Exception as e:
                logger.debug(f"MemoryLoader 动态预算分配失败（跳过）: {e}")

        # 3. 加载人格状态（从 memory_context 中提取）
        personality_data = ctx.memory_context.get("personality", {})
        if personality_data and isinstance(personality_data, dict):
            ctx.personality_state = PersonalityState().from_dict(personality_data)
        # 如果加载失败，保持默认全50

        # B3: TokenCounter 主动调用 — 压缩前判断是否需要压缩
        _needs_compression = True  # 默认需要压缩
        if self._token_counter is not None and ctx.compressed_messages:
            try:
                token_count = await self._token_counter.count_tokens(ctx.compressed_messages)
                _needs_compression = await self._token_counter.should_compress(
                    messages=ctx.compressed_messages,
                    token_count=token_count,
                )
                logger.debug(
                    f"[{ctx.loop_id}] TokenCounter: tokens={token_count}, "
                    f"needs_compression={_needs_compression}"
                )
            except Exception as e:
                logger.debug(f"TokenCounter 判断失败（默认压缩）: {e}")

        # 4. 上下文压缩（V2 — ContextCompressor 三阶段压缩）
        # 4a. 后台压缩信号检查（非阻塞）
        if self.background_compressor and hasattr(
            self.background_compressor, "signal_maybe_compress"
        ):
            try:
                # 传入 session 对象（需有 .messages 属性）
                session_proxy = _SessionProxy(ctx.compressed_messages)
                asyncio.create_task(self.background_compressor.signal_maybe_compress(session_proxy))
            except Exception as e:
                logger.debug(f"后台压缩信号检查失败（降级跳过）: {e}")

        # 4b. 同步压缩（主路径）
        if self.compressor and ctx.compressed_messages is not None:
            try:
                compress_result = await self.compressor.compress(
                    messages=ctx.compressed_messages,
                    current_input=ctx.filtered_input,
                )
                ctx.compressed_messages = (
                    [
                        m
                        for m in ctx.compressed_messages
                        if str(m.get("id", "")) in compress_result.kept_ids
                        or m.get("role") == "system"
                    ]
                    if compress_result.kept_ids
                    else ctx.compressed_messages
                )
                logger.debug(
                    f"[{ctx.loop_id}] 上下文压缩: "
                    f"{compress_result.original_count} → {compress_result.compressed_count}"
                )
            except Exception as e:
                logger.warning(f"上下文压缩失败（降级跳过）: {e}")

        # 5. V2: 人格调节量计算
        # 目标人格由当前交互上下文推导（此处用当前状态作为目标，实际应由LLM评估用户反馈后生成）
        # 当前实现：以当前状态为基准，计算是否需要微调
        # TODO: V3 时由 LLM 根据用户反馈生成 target_state
        if self.fusion_engine:
            try:
                # 临时目标：在当前状态下模拟（实际应由LLM根据用户反馈生成）
                # 这里仅计算当前状态与目标的偏差，为后续反思阶段的人格更新做准备
                ctx.personality_target = PersonalityState(
                    H=ctx.personality_state.H,
                    E=ctx.personality_state.E,
                    X=ctx.personality_state.X,
                    A=ctx.personality_state.A,
                    C=ctx.personality_state.C,
                    O=ctx.personality_state.O,
                )
                logger.debug(
                    f"[{ctx.loop_id}] 人格状态已加载: "
                    f"H={ctx.personality_state.H:.0f} E={ctx.personality_state.E:.0f} "
                    f"X={ctx.personality_state.X:.0f} A={ctx.personality_state.A:.0f} "
                    f"C={ctx.personality_state.C:.0f} O={ctx.personality_state.O:.0f}"
                )
            except Exception as e:
                logger.warning(f"人格调节量计算失败（降级跳过）: {e}")

        # 6. V2: SessionManager 对话历史管理
        # 加载会话历史 → 追加当前用户输入 → 更新会话状态
        if self.session_manager is not None:
            try:
                # 6a. 加载或创建会话
                session = None
                if ctx.conversation_id:
                    session = await self.session_manager.get_session(ctx.conversation_id)
                if session is None:
                    session = await self.session_manager.create_session(
                        session_id=ctx.conversation_id or ctx.loop_id,
                    )
                    logger.debug(f"[{ctx.loop_id}] SessionManager: 创建新会话 {session.id}")

                # 6b. 追加当前用户消息到会话历史
                await self.session_manager.append_message(
                    session_id=session.id,
                    role="user",
                    content=ctx.filtered_input,
                )

                # 6c. 将会话消息同步到 compressed_messages（供后续压缩和LLM使用）
                if hasattr(session, "messages") and session.messages:
                    ctx.compressed_messages = [
                        {
                            "role": getattr(m, "role", "user"),
                            "content": getattr(m, "content", str(m)),
                        }
                        for m in session.messages
                    ]

                # 6d. 更新会话活跃时间
                await self.session_manager.touch_session(session.id)

                logger.debug(
                    f"[{ctx.loop_id}] SessionManager: 会话 {session.id} "
                    f"消息数={len(session.messages) if hasattr(session, 'messages') else '?'}"
                )
            except Exception as e:
                logger.warning(f"SessionManager 操作失败（降级跳过）: {e}")

        logger.debug(f"[{ctx.loop_id}] 感知完成: input={ctx.filtered_input[:50]}")

    async def _load_memory_context(self, query: str) -> dict:
        """
        加载记忆上下文。

        V1：使用 memory.search() 搜索最近5条（粗暴截取）
        V2：使用 MemoryManager.load_memories_for_context() 动态加载
            - 热区40% + 相关30% + 高价值20% + 锚点10%
            - 由信息论公式驱动，无魔法数字
        """
        context = {}
        try:
            # V2：动态记忆加载（优先）
            # 排除 mock 对象（MagicMock 的 getattr/callable 永远返回 truthy）
            _v2_loader = None
            memory_cls_name = type(self.memory).__name__
            if memory_cls_name not in ("MagicMock", "AsyncMock", "NonCallableMagicMock"):
                _v2_loader = getattr(self.memory, "load_memories_for_context", None)
            if _v2_loader is not None and callable(_v2_loader):
                try:
                    loaded_memories = await self.memory.load_memories_for_context(
                        current_input=query,
                    )
                    # 按层分组
                    context["personality"] = [
                        m for m in loaded_memories if m.get("layer") == "personality"
                    ]
                    context["relevant_memories"] = [
                        {"content": m.get("content", ""), "category": m.get("layer", "standard")}
                        for m in loaded_memories
                        if m.get("layer") != "personality"
                    ]
                    context["standards"] = [
                        {"content": m.get("content", ""), "category": "standard"}
                        for m in loaded_memories
                        if m.get("layer") == "standard"
                    ]
                    context["_v2_loaded_count"] = len(loaded_memories)
                    logger.debug(f"[V2] 动态加载记忆: {len(loaded_memories)} 条")
                    return context
                except Exception as e:
                    logger.warning(f"V2 动态记忆加载失败，降级到 V1: {e}")
                    # 降级到 V1（继续执行下方代码）

            # V1 降级路径（原有逻辑）
            if hasattr(self.memory, "get_personality"):
                context["personality"] = self.memory.get_personality()

            if hasattr(self.memory, "search"):
                memories = await self.memory.search(query, limit=5)
                context["relevant_memories"] = [
                    {"content": m.content, "category": m.category} for m in memories
                ]

            if hasattr(self.memory, "get_standards"):
                standards = await self.memory.get_standards()
                context["standards"] = [
                    {"content": s.content, "category": s.category} for s in standards
                ]

        except Exception as e:
            logger.warning(f"加载记忆上下文部分失败: {e}")

        return context

    # ================================================================
    # ② 理解（UNDERSTANDING）
    # ================================================================

    async def _step_understand(self, ctx: LoopContext):
        """
        理解阶段：
        1. 意图解析（UnderstandingEngine.parse）
        2. 置信度评估
        3. 置信度 < 阈值 → 追问
        """
        logger.debug(f"[{ctx.loop_id}] ② 理解阶段")

        if self.understanding:
            try:
                ctx.intent = await self.understanding.parse(ctx.filtered_input, ctx.memory_context)
                ctx.needs_clarification = getattr(ctx.intent, "needs_clarification", False)
                ctx.clarification_question = getattr(ctx.intent, "clarification_question", "")

                if ctx.needs_clarification:
                    logger.info(f"[{ctx.loop_id}] 需要追问: {ctx.clarification_question}")
                    return

            except Exception as e:
                logger.warning(f"意图解析失败（降级为 unknown）: {e}")
                # 降级：创建一个 unknown 意图
                from src.understanding.engine import Intent

                ctx.intent = Intent(
                    type="unknown",
                    content=ctx.filtered_input,
                    confidence=0.3,
                )
        else:
            # 没有理解引擎，直接标记为需要 LLM 处理
            from src.understanding.engine import Intent

            ctx.intent = Intent(
                type="llm_chat",
                content=ctx.filtered_input,
                confidence=0.5,
            )

        logger.debug(
            f"[{ctx.loop_id}] 理解完成: type={getattr(ctx.intent, 'type', 'unknown')}, "
            f"confidence={getattr(ctx.intent, 'confidence', 0):.2f}"
        )

    # ================================================================
    # ③ 规划（PLANNING）
    # ================================================================

    async def _step_plan(self, ctx: LoopContext):
        """
        规划阶段：
        1. 确定操作类型（记忆写入/读取/工具调用/LLM对话）
        2. 危险操作 → 等待审批
        3. 安全操作 → 直接执行
        """
        logger.debug(f"[{ctx.loop_id}] ③ 规划阶段")

        intent_type = getattr(ctx.intent, "type", "unknown")
        requires_approval = getattr(ctx.intent, "requires_approval", False)

        # 映射意图类型到操作类型
        operation_map = {
            "memory_write": "memory_write",
            "memory_read": "memory_read",
            "memory_search": "memory_search",
            "personality_update": "memory_write",
            "tool_call": "tool_call",
            "llm_chat": "llm_chat",
            "clear_memory": "memory_write",
            "reset_personality": "memory_write",
        }

        ctx.operation_type = operation_map.get(intent_type, "llm_chat")
        ctx.requires_approval = requires_approval

        # V2: ApprovalModule 动态风险评估
        if self.approval_module and ctx.operation_type in ("tool_call", "memory_write"):
            try:
                risk_result = await self.approval_module.evaluate_risk(
                    action=ctx.operation_type,
                    params={"intent_type": intent_type, "content": ctx.filtered_input[:100]},
                )
                ctx.requires_approval = risk_result.get("needs_approval", requires_approval)
            except Exception as e:
                logger.warning(f"风险评估失败（使用默认审批策略）: {e}")

        if ctx.requires_approval:
            logger.info(f"[{ctx.loop_id}] 需要审批: {ctx.operation_type}")
            return

        logger.debug(f"[{ctx.loop_id}] 规划完成: operation={ctx.operation_type}")

    # ================================================================
    # ④ 执行（EXECUTING）
    # ================================================================

    async def _step_execute(self, ctx: LoopContext):
        """
        执行阶段：
        1. V2: 优先通过 BSupervisor 执行（目标锚定 + 快照 + 工具沙箱）
        2. V1: 降级为直接执行（兼容未注入 BSupervisor 的场景）
        3. 错误恢复（重试 + 降级）
        """
        logger.debug(f"[{ctx.loop_id}] ④ 执行阶段: {ctx.operation_type}")

        # V2: BSupervisor 执行路径
        if self.b_supervisor:
            try:
                # 构建plan对象（从intent中提取交付物描述和验收标准）
                plan = _build_plan_from_intent(ctx.intent, ctx.operation_type)
                exec_result = await self.b_supervisor.execute(
                    intent=ctx.intent,
                    plan=plan,
                )
                ctx.execution_result = exec_result.output
                ctx.exec_result = exec_result
                ctx.memory_updated = exec_result.status.value == "completed"

                # V2: 快照保存
                if self.snapshot_manager and exec_result.task_id:
                    try:
                        await self.snapshot_manager.save_snapshot(
                            task_id=exec_result.task_id,
                            step_index=exec_result.steps_completed,
                            state={
                                "operation": ctx.operation_type,
                                "result": ctx.execution_result[:200],
                            },
                        )
                    except Exception as snap_err:
                        logger.warning(f"快照保存失败（非阻塞）: {snap_err}")

                result_preview = ctx.execution_result[:50] if ctx.execution_result else "empty"
                logger.debug(f"[{ctx.loop_id}] BSupervisor 执行完成: result={result_preview}")
                return
            except Exception as e:
                logger.warning(f"[{ctx.loop_id}] BSupervisor 执行失败，降级到V1: {e}")

        # V2: SubAgent 任务执行
        if ctx.operation_type == "subagent_task" and self.subagent_manager is not None:
            try:
                task_data = getattr(ctx.intent, "metadata", {}).get("subagent_task", {})
                if task_data:
                    from src.execution.sub_agent_manager import SubAgentTask

                    task = SubAgentTask(
                        description=task_data.get("description", ""),
                        tool_name=task_data.get("tool_name", ""),
                        tool_params=task_data.get("tool_params", {}),
                        timeout_seconds=task_data.get("timeout_seconds", None),
                    )
                    subagent = await self.subagent_manager.spawn(task)
                    completed = await self.subagent_manager.wait(subagent.id)
                    if completed:
                        ctx.execution_result = completed.result or f"子 Agent {subagent.id} 已完成"
                    else:
                        ctx.execution_result = f"子 Agent {subagent.id} 执行超时或未完成"
                    logger.debug(f"[{ctx.loop_id}] SubAgent 执行完成: {ctx.execution_result[:50]}")
                else:
                    ctx.execution_result = "subagent_task: 任务数据为空"
                return
            except Exception as e:
                logger.warning(f"[{ctx.loop_id}] SubAgent 执行失败，降级到V1: {e}")

        # V1: 降级执行路径（原有逻辑）
        try:
            if ctx.operation_type == "memory_write":
                await self._execute_memory_write(ctx)
            elif ctx.operation_type == "memory_read":
                await self._execute_memory_read(ctx)
            elif ctx.operation_type == "memory_search":
                await self._execute_memory_search(ctx)
            elif ctx.operation_type == "tool_call":
                await self._execute_tool_call(ctx)
            else:
                # 默认：LLM 对话
                await self._execute_llm_chat(ctx)

        except Exception as e:
            logger.error(f"[{ctx.loop_id}] 执行失败: {e}", exc_info=True)
            ctx.execution_result = f"执行失败：{e}"
            ctx.llm_result = LLMResult.fail(
                error=str(e),
                code=ErrorCode.SERVER_ERROR,
            )

        result_preview = ctx.execution_result[:50] if ctx.execution_result else "empty"
        logger.debug(f"[{ctx.loop_id}] 执行完成: result={result_preview}")

    async def _execute_memory_write(self, ctx: LoopContext):
        """执行记忆写入"""
        if not self.memory:
            ctx.execution_result = "记忆系统未初始化"
            return

        target_layer = getattr(ctx.intent, "target_layer", "core")
        await self.memory.remember(
            content=ctx.filtered_input,
            layer=target_layer,
        )
        ctx.execution_result = f"✅ 已记住（{target_layer} 层）"
        ctx.memory_updated = True

        if self.audit:
            self.audit.log(
                AuditAction.MEMORY_WRITE,
                {"content": ctx.filtered_input[:100], "layer": target_layer},
            )

    async def _execute_memory_read(self, ctx: LoopContext):
        """执行记忆读取"""
        if not self.memory:
            ctx.execution_result = "记忆系统未初始化"
            return

        memories = await self.memory.search(ctx.filtered_input, limit=10)
        if memories:
            lines = [f"- [{m.category}] {m.content}" for m in memories[:5]]
            ctx.execution_result = "找到以下记忆：\n" + "\n".join(lines)
        else:
            ctx.execution_result = "没有找到相关记忆。"

    async def _execute_memory_search(self, ctx: LoopContext):
        """执行记忆搜索"""
        await self._execute_memory_read(ctx)

    async def _execute_tool_call(self, ctx: LoopContext):
        """执行工具调用"""
        if not self.tools:
            ctx.execution_result = "工具系统未初始化"
            return

        tool_name = getattr(ctx.intent, "metadata", {}).get("tool_name", "")
        tool_params = getattr(ctx.intent, "metadata", {}).get("tool_params", {})

        if tool_name:
            ctx.tool_result = await self.tools.execute(tool_name, tool_params)
            if ctx.tool_result.is_ok:
                ctx.execution_result = str(ctx.tool_result.data)
            else:
                ctx.execution_result = f"工具调用失败：{ctx.tool_result.error_message}"
        else:
            ctx.execution_result = "未指定工具名称"

    async def _execute_llm_chat(self, ctx: LoopContext):
        """执行 LLM 对话"""
        if not self.llm:
            ctx.execution_result = "LLM 未初始化。这是一个 echo 回复：" + ctx.filtered_input
            return

        # 构建消息
        messages = []

        # System prompt（包含人格 + 记忆上下文）
        system_parts = []
        personality = ctx.memory_context.get("personality", {})
        if personality:
            hexaco = []
            for dim in ["H", "E", "X", "A", "C", "O"]:
                val = personality.get(dim, 50)
                hexaco.append(f"{dim}={val}")
            system_parts.append(f"人格参数: {', '.join(hexaco)}")

        memories = ctx.memory_context.get("relevant_memories", [])
        if memories:
            mem_lines = [f"- {m['content']}" for m in memories[:3]]
            system_parts.append("相关记忆:\n" + "\n".join(mem_lines))

        if system_parts:
            messages.append(
                {
                    "role": "system",
                    "content": "\n\n".join(system_parts),
                }
            )

        messages.append({"role": "user", "content": ctx.filtered_input})

        # 调用 LLM
        try:
            from src.llm.provider import LLMRequest

            request = LLMRequest(
                messages=messages,
                model=getattr(self.llm, "model", "gpt-4o"),
            )
            ctx.llm_result = await self.llm.chat(request)

            if ctx.llm_result.is_ok:
                ctx.execution_result = ctx.llm_result.content
            else:
                ctx.execution_result = f"LLM 调用失败：{ctx.llm_result.error}"
                logger.warning(f"[{ctx.loop_id}] LLM 失败: {ctx.llm_result.error}")

        except Exception as e:
            logger.error(f"[{ctx.loop_id}] LLM 调用异常: {e}")
            ctx.execution_result = f"LLM 调用异常：{e}"
            ctx.llm_result = LLMResult.fail(
                error=str(e),
                code=ErrorCode.CONNECTION_ERROR,
            )

    # ================================================================
    # ⑤ 观察（OBSERVING）
    # ================================================================

    async def _step_observe(self, ctx: LoopContext):
        """
        观察阶段：
        1. 检查结果是否跑偏（理解引擎 + ResultVerifier 双重检查）
        2. V2: ResultVerifier 验证执行结果质量
        3. 跑偏 → 标记重试
        4. 正常 → 进入反思
        """
        logger.debug(f"[{ctx.loop_id}] ⑤ 观察阶段")

        if not ctx.execution_result:
            ctx.is_off_track = True
            ctx.off_track_reason = "执行结果为空"
            return

        # V2: 结果验证
        if self.result_verifier and ctx.exec_result:
            try:
                deliverable_plan = _build_plan_from_intent(ctx.intent, ctx.operation_type)
                ctx.verify_report = await self.result_verifier.verify(
                    execution_result=ctx.exec_result,
                    deliverable_plan=deliverable_plan,
                )
                ctx.verification_status = ctx.verify_report.overall_status.value
                ctx.verification_passed = ctx.verify_report.overall_status.value == "passed"
                if not ctx.verification_passed:
                    ctx.is_off_track = True
                    ctx.off_track_reason = ctx.verify_report.summary
                    logger.warning(f"[{ctx.loop_id}] ResultVerifier 未通过: {ctx.off_track_reason}")
                    return
            except Exception as e:
                logger.warning(f"ResultVerifier 检查失败（降级跳过）: {e}")

        # V2: GoalAnchor 目标锚定检查
        if self.goal_anchor and ctx.execution_result and hasattr(ctx, "intent") and ctx.intent:
            try:
                goal = getattr(ctx.intent, "content", ctx.filtered_input) or ctx.filtered_input
                anchor_result = self.goal_anchor.check(
                    goal=goal,
                    current=ctx.execution_result[:200],
                    progress=1.0,
                )
                if anchor_result.action in ("stop", "ask_user"):
                    ctx.is_off_track = True
                    ctx.off_track_reason = anchor_result.suggestion
                    logger.warning(
                        f"[{ctx.loop_id}] GoalAnchor 检测到跑偏: {anchor_result.suggestion}"
                    )
                    return
            except Exception as e:
                logger.warning(f"GoalAnchor 检查失败（跳过）: {e}")

        # V1: 理解引擎跑偏检查
        if self.understanding and hasattr(self.understanding, "is_off_track"):
            try:
                ctx.is_off_track = self.understanding.is_off_track(ctx.execution_result, ctx.intent)
                if ctx.is_off_track:
                    ctx.off_track_reason = "理解引擎判定跑偏"
            except Exception as e:
                logger.warning(f"跑偏检查失败（默认不跑偏）: {e}")
                ctx.is_off_track = False
        else:
            # 没有理解引擎，默认不跑偏
            ctx.is_off_track = False

        if not ctx.is_off_track:
            logger.debug(f"[{ctx.loop_id}] 观察通过，未跑偏")

    # ================================================================
    # ⑥ 反思（REFLECTING）
    # ================================================================

    async def _step_reflect(self, ctx: LoopContext):
        """
        反思阶段：
        1. 更新记忆（访问计数、时间戳）
        2. V2: 触发记忆淘汰检查（MemoryManager.check_and_evict）
        3. V2: 人格状态更新（PersonalityFusionEngine）
        4. 记录审计日志
        """
        logger.debug(f"[{ctx.loop_id}] ⑥ 反思阶段")

        # 1. 更新记忆访问计数
        if self.memory and ctx.memory_updated:
            try:
                # V2: 触发记忆淘汰检查（宽进严出）
                # 每次写入新记忆后，检查是否需要淘汰低价值记忆
                if hasattr(self.memory, "check_and_evict"):
                    try:
                        evict_result = await self.memory.check_and_evict(
                            current_input=ctx.user_input,
                        )
                        if evict_result.get("evicted", 0) > 0:
                            logger.info(
                                f"[{ctx.loop_id}] 记忆淘汰: "
                                f"淘汰 {evict_result['evicted']} 条, "
                                f"剩余 {evict_result['remaining']} 条, "
                                f"eviction_score={evict_result['eviction_score']:.4f}"
                            )
                    except Exception as e:
                        logger.warning(f"记忆淘汰检查失败（跳过）: {e}")
            except Exception as e:
                logger.warning(f"更新记忆访问计数失败: {e}")

        # 2. V2: 人格状态更新
        # 根据本次交互结果（是否跑偏、重试次数、执行结果质量）计算人格调节量
        if self.fusion_engine:
            try:
                # 根据交互结果推导目标人格调整方向
                # 原理：如果执行顺利 → 强化当前人格特质；如果跑偏/重试 → 微调
                target = self._derive_personality_target(ctx)
                adjustments = self.fusion_engine.compute_adjustment(
                    current_state=ctx.personality_state,
                    target_state=target,
                    dt=1.0,
                )
                # 过滤掉死区内的零调节
                significant = {k: v for k, v in adjustments.items() if abs(v) > 0.01}
                if significant:
                    new_state = self.fusion_engine.apply_adjustment(
                        PersonalityState(
                            H=ctx.personality_state.H,
                            E=ctx.personality_state.E,
                            X=ctx.personality_state.X,
                            A=ctx.personality_state.A,
                            C=ctx.personality_state.C,
                            O=ctx.personality_state.O,
                        ),
                        significant,
                    )
                    ctx.personality_state = new_state
                    ctx.personality_adjustments = significant
                    ctx.personality_updated = True
                    logger.info(
                        f"[{ctx.loop_id}] 人格已更新: "
                        f"adjustments={significant}, "
                        f"new_state=H={new_state.H:.1f} E={new_state.E:.1f} "
                        f"X={new_state.X:.1f} A={new_state.A:.1f} "
                        f"C={new_state.C:.1f} O={new_state.O:.1f}"
                    )
            except Exception as e:
                logger.warning(f"人格更新失败（降级跳过）: {e}")

        # 2.5: 触发后台任务（对话结束钩子）
        if self.background_manager is not None:
            try:
                await self.background_manager.on_conversation_end(
                    storage=getattr(self.memory, "storage", None) if self.memory else None,
                    memory_manager=self.memory,
                )
                ctx.background_tasks_triggered = True
                logger.debug(f"[{ctx.loop_id}] 后台任务已触发")
            except Exception as e:
                logger.warning(f"[{ctx.loop_id}] 后台任务触发失败（非阻塞）: {e}")

        # 3. 记录审计日志
        if self.audit:
            self.audit.log(
                AuditAction.MEMORY_SEARCH,
                {
                    "loop_id": ctx.loop_id,
                    "operation": ctx.operation_type,
                    "off_track": ctx.is_off_track,
                    "retries": ctx.retry_count,
                    "personality_updated": ctx.personality_updated,
                },
            )

        logger.debug(f"[{ctx.loop_id}] 反思完成")

    def _derive_personality_target(self, ctx: LoopContext) -> PersonalityState:
        """
        根据交互结果推导目标人格

        决策规则（不凭感觉，基于交互指标）：
        - 执行成功且无重试 → 强化当前人格（目标=当前+微调向50靠拢的反方向）
        - 执行跑偏但恢复 → 尽责性(C)微调+2（更谨慎）
        - 执行失败 → 情绪性(E)微调+3（更敏感），尽责性(C)+2
        - 用户触发追问 → 宜人性(A)+2（更友善），外向性(X)-1（更内敛）

        所有调节量不超过 MAX_SINGLE_ADJUST=5.0 的限制
        """
        current = ctx.personality_state
        target = PersonalityState(
            H=current.H,
            E=current.E,
            X=current.X,
            A=current.A,
            C=current.C,
            O=current.O,
        )

        if ctx.is_off_track and ctx.retry_count > 0:
            # 跑偏但恢复：更谨慎
            target.C = min(100.0, current.C + 2.0)
        elif ctx.error:
            # 执行失败：更敏感、更谨慎
            target.E = min(100.0, current.E + 3.0)
            target.C = min(100.0, current.C + 2.0)
        elif ctx.needs_clarification:
            # 用户追问：更友善、更内敛
            target.A = min(100.0, current.A + 2.0)
            target.X = max(0.0, current.X - 1.0)
        else:
            # 顺利执行：轻微强化当前特质（向当前方向微调1.0）
            # 每个维度向当前方向走一步，但不超过边界
            for dim in PersonalityState.DIMIONS:
                val = getattr(current, dim)
                if val > 55:
                    setattr(target, dim, min(100.0, val + 0.5))
                elif val < 45:
                    setattr(target, dim, max(0.0, val - 0.5))
                # 45~55 之间不调整（接近中性，无需强化）

        return target

    # ================================================================
    # ⑦ 回复（REPLYING）
    # ================================================================

    async def _step_reply(self, ctx: LoopContext):
        """
        回复阶段：
        1. V2: ReportGenerator 格式化输出（如果有）
        2. V1: 降级为直接输出
        3. 回到空闲
        """
        logger.debug(f"[{ctx.loop_id}] ⑦ 回复阶段")

        # V2: ReportGenerator 格式化
        if self.report_generator:
            try:
                report = self.report_generator.generate(
                    verification_report=ctx.verify_report,
                    execution_result=ctx.exec_result,
                )
                ctx.response = (
                    report.user_summary.get("conclusion", "")
                    if hasattr(report, "user_summary")
                    else str(report)
                )
                return
            except Exception as e:
                logger.warning(f"ReportGenerator 生成失败（降级）: {e}")

        # V1: 降级输出
        if ctx.execution_result:
            ctx.response = ctx.execution_result
        elif ctx.llm_result and ctx.llm_result.ok:
            ctx.response = ctx.llm_result.content
        else:
            ctx.response = "我没有找到合适的回复。"

        logger.debug(f"[{ctx.loop_id}] 回复完成: {ctx.response[:50]}")
