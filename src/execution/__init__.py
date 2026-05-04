"""
执行层 — V2 新增

模块：
- GoalAnchor: 目标锚定器
- SnapshotManager: 快照管理器
- ToolRegistry: 工具注册表 + 三级沙箱
- BSupervisor: 执行监督器
"""

from src.execution.b_supervisor import (
    BSupervisor,
    ExecutionResult,
    ExecutionStatus,
    StepStatus,
    TaskStep,
)
from src.execution.goal_anchor import AnchorResult, GoalAnchor
from src.execution.snapshot_manager import SnapshotManager, TaskSnapshot
from src.execution.tool_registry import ToolDefinition, ToolLevel, ToolRegistry, ToolResult

__all__ = [
    "GoalAnchor",
    "AnchorResult",
    "SnapshotManager",
    "TaskSnapshot",
    "ToolRegistry",
    "ToolDefinition",
    "ToolResult",
    "ToolLevel",
    "BSupervisor",
    "ExecutionResult",
    "ExecutionStatus",
    "StepStatus",
    "TaskStep",
]
