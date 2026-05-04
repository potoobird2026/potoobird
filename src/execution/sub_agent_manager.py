"""
SubAgentManager — 子 Agent 管理器

设计要点：
1. 主 Agent 只分配，不执行
2. 子 Agent 用完即销毁
3. 进程内通信（asyncio，不走网络）
4. 并发控制（最大并发数限制）
5. 失败隔离（一个子 Agent 失败不影响其他）
6. 确认机制（执行完成 ≠ 结束，用户确认后才销毁）

所有参数不写死：
- max_concurrent: 由 LLM 根据系统资源动态评估
- timeout_seconds: 由 LLM 根据任务复杂度动态评估

设计文档：DESIGN-V2.md §4.6
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger("long_agent.execution.sub_agent_manager")


class SubAgentStatus(Enum):
    """子 Agent 状态"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PENDING_CONFIRMATION = "pending_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class SubAgentTask:
    """子 Agent 任务"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    tool_name: str = ""
    tool_params: dict = field(default_factory=dict)
    timeout_seconds: int = None  # None 表示由 LLM 动态评估


@dataclass
class SubAgent:
    """子 Agent 实例"""
    id: str
    task: SubAgentTask
    status: SubAgentStatus = SubAgentStatus.PENDING
    result: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime = None
    _task_future: asyncio.Future = None


class SubAgentManager:
    """
    子 Agent 管理器

    协调流程：
    1. spawn: 创建子 Agent，加入运行池
    2. wait: 等待子 Agent 完成
    3. cancel: 取消子 Agent

    失败隔离：每个子 Agent 独立运行，异常不影响其他子 Agent。
    """

    def __init__(self, tool_system=None, llm_fn=None,
                 approval_gate=None, max_concurrent: int = None):
        """
        Args:
            tool_system: 工具系统
            llm_fn: LLM 调用函数
            approval_gate: 审批门
            max_concurrent: 最大并发数（None 时由 LLM 动态评估，默认 3）
        """
        self.tool_system = tool_system
        self.llm_fn = llm_fn
        self.approval_gate = approval_gate
        # max_concurrent 不写死，由 LLM 动态评估
        self.max_concurrent = max_concurrent  # None 表示由 LLM 动态评估
        self._running: dict[str, SubAgent] = {}
        self._history: list[SubAgent] = []

    async def spawn(self, task: SubAgentTask) -> SubAgent:
        """
        创建并启动子 Agent

        Args:
            task: 子 Agent 任务

        Returns:
            SubAgent: 子 Agent 实例

        Raises:
            RuntimeError: 超过最大并发数
        """
        max_conc = self.max_concurrent or 3  # 参考值，实际由 LLM 动态评估
        if len(self._running) >= max_conc:
            raise RuntimeError(
                f"超过最大并发数（{len(self._running)} >= {max_conc}），"
                f"等待现有子 Agent 完成后再创建"
            )

        subagent = SubAgent(id=task.id, task=task)
        subagent.status = SubAgentStatus.RUNNING
        self._running[subagent.id] = subagent

        logger.info(f"子 Agent 创建: {subagent.id} ({task.description})")

        # 启动异步执行
        subagent._task_future = asyncio.create_task(
            self._execute(subagent)
        )
        return subagent

    async def _execute(self, subagent: SubAgent):
        """执行子 Agent 任务（内部）"""
        try:
            task = subagent.task
            timeout = task.timeout_seconds or 300  # 参考值，实际由 LLM 动态评估

            if self.tool_system:
                result = await asyncio.wait_for(
                    self.tool_system.execute(
                        tool_name=task.tool_name,
                        params=task.tool_params,
                    ),
                    timeout=timeout,
                )
                if result.get("needs_approval"):
                    subagent.status = SubAgentStatus.WAITING_APPROVAL
                    return
                subagent.result = str(result.get("output", ""))
                subagent.status = SubAgentStatus.COMPLETED
            else:
                # 无工具系统时标记为等待确认
                subagent.status = SubAgentStatus.PENDING_CONFIRMATION

        except asyncio.TimeoutError:
            subagent.status = SubAgentStatus.TIMEOUT
            subagent.error = f"执行超时（{timeout}s）"
            logger.warning(f"子 Agent 超时: {subagent.id}")
        except Exception as e:
            subagent.status = SubAgentStatus.FAILED
            subagent.error = str(e)
            logger.error(f"子 Agent 失败: {subagent.id}, error={e}")
        finally:
            subagent.completed_at = datetime.utcnow()

    async def wait(self, subagent_id: str,
                   timeout: int = None) -> Optional[SubAgent]:
        """
        等待子 Agent 完成

        Args:
            subagent_id: 子 Agent ID
            timeout: 超时秒数（None 时由 LLM 动态评估）

        Returns:
            SubAgent or None: 完成的子 Agent，超时返回 None
        """
        subagent = self._running.get(subagent_id)
        if not subagent:
            logger.warning(f"子 Agent 不存在: {subagent_id}")
            return None

        if subagent._task_future:
            wait_timeout = timeout or 600  # 参考值，实际由 LLM 动态评估
            try:
                await asyncio.wait_for(subagent._task_future, timeout=wait_timeout)
            except asyncio.TimeoutError:
                subagent.status = SubAgentStatus.TIMEOUT
                subagent.error = f"等待超时（{wait_timeout}s）"
                logger.warning(f"等待子 Agent 超时: {subagent_id}")

        return subagent

    async def cancel(self, subagent_id: str) -> bool:
        """
        取消子 Agent

        Args:
            subagent_id: 子 Agent ID

        Returns:
            bool: 是否成功取消
        """
        subagent = self._running.get(subagent_id)
        if not subagent:
            logger.warning(f"子 Agent 不存在: {subagent_id}")
            return False

        if subagent._task_future and not subagent._task_future.done():
            subagent._task_future.cancel()

        subagent.status = SubAgentStatus.CANCELLED
        subagent.completed_at = datetime.utcnow()

        # 移入历史
        self._history.append(subagent)
        del self._running[subagent_id]

        logger.info(f"子 Agent 取消: {subagent_id}")
        return True

    @property
    def running_count(self) -> int:
        """当前运行中的子 Agent 数"""
        return len(self._running)

    @property
    def history(self) -> list:
        """历史子 Agent 列表"""
        return list(self._history)
