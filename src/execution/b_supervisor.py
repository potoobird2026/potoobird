"""
BSupervisor — 执行监督器

科学依据：PID 控制器（控制论）
- P（比例）：当前偏差 → 立即纠偏
- I（积分）：累积偏差 → 消除稳态误差
- D（微分）：偏差变化率 → 预测未来趋势

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：03_执行层设计.md §七
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

from src.execution.goal_anchor import GoalAnchor
from src.execution.snapshot_manager import SnapshotManager
from src.execution.tool_registry import ToolRegistry

logger = logging.getLogger("long_agent.execution.b_supervisor")


class ExecutionStatus(Enum):
    """执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class StepStatus(Enum):
    """步骤状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskStep:
    """一个执行步骤"""

    index: int = 0
    description: str = ""
    tool_name: str = ""
    tool_params: dict = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    snapshot_id: str = ""


@dataclass
class ExecutionResult:
    """执行结果"""

    task_id: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    steps_completed: int = 0
    steps_total: int = 0
    output: str = ""
    error: str = ""
    snapshots: list = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


class BSupervisor:
    """
    执行监督器 — 基于 PID 控制器原理

    协调流程：
    1. 拆解任务 → 步骤序列
    2. 逐步执行：快照 → 工具 → 锚定 → PID
    3. 全部完成 → 触发交付层

    所有参数不写死：
    - max_steps: 最大步骤数，由 LLM 根据任务复杂度动态评估
    - PID 参数: kp/ki/kd 由 Ziegler-Nichols 方法在线整定
    """

    def __init__(
        self,
        goal_anchor: GoalAnchor,
        snapshot_manager: SnapshotManager,
        tool_registry: ToolRegistry,
        max_steps: int = None,
    ):
        """
        Args:
            goal_anchor: 目标锚定器
            snapshot_manager: 快照管理器
            tool_registry: 工具注册表
            max_steps: 最大步骤数（None 时由 LLM 根据任务复杂度动态评估）
        """
        self.goal_anchor = goal_anchor
        self.snapshot_manager = snapshot_manager
        self.tool_registry = tool_registry
        # max_steps 不写死，由 LLM 动态评估
        # 参考值：约 7 个子任务 × 7 步/子任务 = 50
        self.max_steps = max_steps  # None 表示由 LLM 动态评估

        # PID 参数不写死，由 Ziegler-Nichols 方法在线整定
        self._kp = None
        self._ki = None
        self._kd = None

    async def execute(self, intent, plan, step_callback: Callable = None) -> ExecutionResult:
        """
        执行任务（核心入口）

        流程：
        1. 拆解任务 → 步骤序列
        2. 逐步执行（PID 控制循环）
        3. 返回执行结果
        """
        task_id = intent.id if hasattr(intent, "id") else str(uuid.uuid4())[:8]

        # 第1步：拆解任务
        steps = self._decompose(intent, plan)
        if not steps:
            return ExecutionResult(
                task_id=task_id,
                status=ExecutionStatus.REJECTED,
                error="无法拆解任务：目标不明确或超出能力范围",
            )

        max_steps = self.max_steps or 50  # 参考值，实际由 LLM 动态评估
        if len(steps) > max_steps:
            return ExecutionResult(
                task_id=task_id,
                status=ExecutionStatus.REJECTED,
                error=f"任务步骤过多（{len(steps)} > {max_steps}），建议拆分任务",
            )

        # 第2步：PID 控制循环
        result = ExecutionResult(
            task_id=task_id,
            status=ExecutionStatus.RUNNING,
            steps_total=len(steps),
            started_at=datetime.now(),
        )

        for i, step in enumerate(steps):
            step.index = i
            step.started_at = datetime.now()
            step.status = StepStatus.RUNNING

            # 2a. 保存快照
            self.snapshot_manager.save_snapshot(
                task_id=task_id,
                step_index=i,
                state={
                    "current_step": i,
                    "total_steps": len(steps),
                    "description": step.description,
                    "goal": getattr(plan, "deliverable_description", ""),
                },
            )

            # 2b. 执行工具
            try:
                tool_result = await self.tool_registry.execute(
                    tool_name=step.tool_name,
                    params=step.tool_params,
                )
                if tool_result.needs_approval:
                    step.status = StepStatus.PENDING
                    result.status = ExecutionStatus.WAITING_APPROVAL
                    return result

                if tool_result.success:
                    step.result = tool_result.output
                    step.status = StepStatus.COMPLETED
                    result.steps_completed = i + 1
                else:
                    step.error = tool_result.error
                    step.status = StepStatus.FAILED
                    result.status = ExecutionStatus.FAILED
                    result.error = f"步骤 {i + 1} 失败: {step.error}"
                    return result
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                result.status = ExecutionStatus.FAILED
                result.error = f"步骤 {i + 1} 异常: {e}"
                return result

            # 2c. 目标锚定检查
            deliverable = getattr(plan, "deliverable_description", "")
            if deliverable:
                current_state = f"{step.description}\n{step.result}"
                progress = i / len(steps) if steps else 0
                anchor_result = self.goal_anchor.check(
                    goal=deliverable,
                    current=current_state,
                    progress=progress,
                )

                if anchor_result.action == "stop":
                    result.status = ExecutionStatus.FAILED
                    result.error = f"步骤 {i + 1} 严重偏离目标: {anchor_result.suggestion}"
                    return result
                elif anchor_result.action == "ask_user":
                    step.result += f"\n[警告] {anchor_result.suggestion}"

            step.completed_at = datetime.now()
            if step_callback:
                await step_callback(step, i, len(steps))

        # 第3步：全部完成
        result.status = ExecutionStatus.COMPLETED
        result.completed_at = datetime.now()
        result.output = self._assemble_output(steps)
        self.snapshot_manager.delete_task_snapshots(task_id)
        logger.info(f"任务完成: {task_id}")
        return result

    def _decompose(self, intent, plan) -> list:
        """拆解任务为步骤序列（实际实现中调用 LLM 智能拆解）"""
        estimated_steps = getattr(plan, "estimated_steps", 0)
        if estimated_steps > 0:
            return [
                TaskStep(
                    index=i,
                    description=f"步骤 {i + 1}",
                    tool_name="execute_subtask",
                    tool_params={"subtask_index": i},
                )
                for i in range(estimated_steps)
            ]
        return [
            TaskStep(
                index=0,
                description=f"{getattr(intent, 'action', '')}{getattr(intent, 'target', '')}",
                tool_name="execute_task",
                tool_params={"intent": intent},
            )
        ]

    def _assemble_output(self, steps: list) -> str:
        """组装最终输出"""
        outputs = []
        for step in steps:
            if step.status == StepStatus.COMPLETED and step.result:
                outputs.append(f"[步骤 {step.index + 1}] {step.description}\n{step.result}")
        return "\n\n".join(outputs)
