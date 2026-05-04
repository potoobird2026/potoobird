"""
ProcessStandard — 流程标准化器

职责：
1. 记录每次任务的标准步骤
2. 积累审批记录，形成标准流程指南
3. 指导未来类似任务

设计原则：
- 每次审批通过的操作都在积累"什么样的操作需要审批"
- 项目结束后可以回顾完整的审批记录
- 形成标准流程指南，指导未来类似任务

设计文档：DESIGN-V2.md §4.7
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("long_agent.execution.process_standard")


@dataclass
class StepRecord:
    """步骤记录"""

    index: int = 0
    description: str = ""
    tool_name: str = ""
    tool_params: dict = field(default_factory=dict)
    result: str = ""
    error: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime = None
    approved: bool = False


@dataclass
class ApprovalRecord:
    """审批记录"""

    step_index: int = 0
    action: str = ""
    approved: bool = False
    approver: str = ""
    reason: str = ""
    risk_score: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ProcessStandard:
    """
    流程标准化器

    通过积累任务执行记录和审批记录，形成标准流程指南。
    同类任务再次执行时，可参考历史标准流程提高效率。
    """

    def __init__(self, memory_manager=None):
        """
        Args:
            memory_manager: 管理器（用于持久化标准流程）
        """
        self.memory = memory_manager
        self._standard_processes: dict[str, list] = {}  # task_type -> [StepRecord]
        self._approval_logs: dict[str, list] = {}  # task_type -> [ApprovalRecord]
        logger.info("ProcessStandard 初始化完成")

    def record_step(self, task_type: str, step: dict):
        """
        记录一个执行步骤

        Args:
            task_type: 任务类型
            step: 步骤数据 dict，包含 index/description/tool_name/tool_params/result/error
        """
        if task_type not in self._standard_processes:
            self._standard_processes[task_type] = []

        record = StepRecord(
            index=step.get("index", 0),
            description=step.get("description", ""),
            tool_name=step.get("tool_name", ""),
            tool_params=step.get("tool_params", {}),
            result=step.get("result", ""),
            error=step.get("error", ""),
        )
        self._standard_processes[task_type].append(record)
        logger.debug(f"步骤记录: task_type={task_type}, step={record.index}")

    def get_standard_process(self, task_type: str) -> list:
        """
        获取标准流程指南

        Args:
            task_type: 任务类型

        Returns:
            list[dict]: 标准步骤列表，每个步骤包含 description/tool_name/params_hint
        """
        records = self._standard_processes.get(task_type, [])
        if not records:
            return []

        return [
            {
                "index": r.index,
                "description": r.description,
                "tool_name": r.tool_name,
                "params_hint": r.tool_params,
                "approved": r.approved,
            }
            for r in records
        ]

    def finalize_task(self, task_type: str, step_log: list, approval_log: list):
        """
        任务完成时，更新标准流程

        Args:
            task_type: 任务类型
            step_log: 步骤记录列表
            approval_log: 审批记录列表
        """
        # 更新标准流程（合并新步骤）
        existing = self._standard_processes.get(task_type, [])
        existing_descriptions = {s.description for s in existing}

        for step_data in step_log:
            desc = step_data.get("description", "")
            if desc and desc not in existing_descriptions:
                record = StepRecord(
                    index=step_data.get("index", 0),
                    description=desc,
                    tool_name=step_data.get("tool_name", ""),
                    tool_params=step_data.get("tool_params", {}),
                    approved=step_data.get("approved", False),
                )
                existing.append(record)
                existing_descriptions.add(desc)

        self._standard_processes[task_type] = existing

        # 记录审批日志
        if approval_log:
            if task_type not in self._approval_logs:
                self._approval_logs[task_type] = []
            for appr_data in approval_log:
                record = ApprovalRecord(
                    step_index=appr_data.get("step_index", 0),
                    action=appr_data.get("action", ""),
                    approved=appr_data.get("approved", False),
                    approver=appr_data.get("approver", ""),
                    reason=appr_data.get("reason", ""),
                    risk_score=appr_data.get("risk_score", 0.0),
                )
                self._approval_logs[task_type].append(record)

        logger.info(
            f"任务流程归档: task_type={task_type}, "
            f"steps={len(step_log)}, approvals={len(approval_log)}"
        )

    def get_approval_log(self, task_type: str = None) -> list:
        """
        获取审批记录

        Args:
            task_type: 任务类型（None 时返回全部）

        Returns:
            list[ApprovalRecord]: 审批记录列表
        """
        if task_type:
            return list(self._approval_logs.get(task_type, []))

        all_records = []
        for records in self._approval_logs.values():
            all_records.extend(records)
        return all_records
