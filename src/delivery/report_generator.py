"""
ReportGenerator — 报告生成器
ConfirmationManager — 任务确认管理器

科学依据：
- 审计学证据链：结论 → 证据 → 建议
- 金字塔原理：先说结论，再说理由
- 渐进式披露：分层信息展示

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：04_交付层设计.md §五 §六
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger("long_agent.delivery")


@dataclass
class DeliveryReport:
    """交付报告 — 分层设计"""

    task_id: str = ""
    conclusion: str = ""
    summary: str = ""
    details: list = field(default_factory=list)
    suggestions: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    evidence_chain: list = field(default_factory=list)
    deviation_history: list = field(default_factory=list)
    compression_record: dict = field(default_factory=dict)
    compression_lessons: list = field(default_factory=list)
    user_summary: dict = field(default_factory=dict)
    tech_detail: dict = field(default_factory=dict)
    active_layer: str = "summary"
    created_at: datetime = field(default_factory=datetime.now)


class ReportGenerator:
    """
    报告生成器 — 金字塔原理 + 分层报告
    """

    def generate(
        self,
        verification_report,
        execution_result=None,
        compression_record: dict = None,
        lessons: list = None,
    ) -> DeliveryReport:
        """生成交付报告"""
        conclusion = self._generate_conclusion(verification_report)
        summary = self._generate_summary(verification_report)
        details = self._generate_details(verification_report)
        suggestions = self._generate_suggestions(verification_report)
        risks = self._generate_risks(verification_report)

        return DeliveryReport(
            task_id=verification_report.task_id,
            conclusion=conclusion,
            summary=summary,
            details=details,
            suggestions=suggestions,
            risks=risks,
            evidence_chain=verification_report.evidence_chain,
            user_summary=self._build_user_summary(verification_report, conclusion),
            tech_detail=self._build_tech_detail(verification_report, details, suggestions, risks),
        )

    def _build_user_summary(self, report, conclusion) -> dict:
        """构建用户摘要层"""
        total_duration = sum(i.duration for i in report.items)
        return {
            "conclusion": conclusion,
            "pass_rate": f"{report.pass_rate:.0%}",
            "total_duration": f"{total_duration:.1f}s",
            "total_items": len(report.items),
            "passed_items": sum(1 for i in report.items if i.status.value == "passed"),
            "failed_items": sum(1 for i in report.items if i.status.value == "failed"),
        }

    def _build_tech_detail(self, report, details, suggestions, risks) -> dict:
        """构建技术详情层"""
        l1_items = [i for i in report.items if i.level.value == 1]
        l2_items = [i for i in report.items if i.level.value == 2]
        l3_items = [i for i in report.items if i.level.value == 3]
        return {
            "l1_static": {"items": l1_items, "pass_rate": self._level_pass_rate(l1_items)},
            "l2_dynamic": {"items": l2_items, "pass_rate": self._level_pass_rate(l2_items)},
            "l3_manual": {"items": l3_items, "pass_rate": self._level_pass_rate(l3_items)},
            "evidence_chain": report.evidence_chain,
            "suggestions": suggestions,
            "risks": risks,
        }

    def _level_pass_rate(self, items) -> str:
        completed = [i for i in items if i.status.value in ("passed", "failed")]
        if not completed:
            return "N/A"
        return f"{sum(1 for i in completed if i.status.value == 'passed') / len(completed):.0%}"

    def _generate_conclusion(self, report) -> str:
        status_map = {
            "passed": "✅ 任务已完成，所有验收标准通过",
            "failed": "❌ 任务未完成，部分验收标准未通过",
            "error": "⚠️ 验证过程出错，结果不确定",
            "skipped": "⏭️ 跳过验证（无验收标准）",
        }
        base = status_map.get(report.overall_status.value, "未知状态")
        if report.items:
            base += f"（通过率 {report.pass_rate:.0%}）"
        return base

    def _generate_summary(self, report) -> str:
        total = len(report.items)
        passed = sum(1 for i in report.items if i.status.value == "passed")
        failed = sum(1 for i in report.items if i.status.value == "failed")
        errors = sum(1 for i in report.items if i.status.value == "error")
        lines = [f"共执行 {total} 项验证：{passed} 项通过，{failed} 项失败，{errors} 项出错。"]
        if report.overall_status.value == "passed":
            lines.append("所有关键验收标准均已通过，交付物可以正常使用。")
        elif report.overall_status.value == "failed":
            failed_items = [i for i in report.items if i.status.value == "failed"]
            lines.append(f"以下 {len(failed_items)} 项未通过：")
            for item in failed_items[:3]:
                lines.append(f"  - {item.criterion}")
        return "\n".join(lines)

    def _generate_details(self, report) -> list:
        details = []
        for item in report.items:
            status_icon = {"passed": "✅", "failed": "❌", "error": "⚠️", "skipped": "⏭️"}.get(
                item.status.value, "❓"
            )
            details.append(
                {
                    "status": f"{status_icon} {item.status.value}",
                    "criterion": item.criterion,
                    "evidence": item.evidence[:100] if item.evidence else "",
                    "error": item.error[:100] if item.error else "",
                    "duration": f"{item.duration:.1f}s",
                }
            )
        return details

    def _generate_suggestions(self, report) -> list:
        if report.overall_status.value == "passed":
            return ["当前无需改进。建议保存代码并进入下一步。"]
        suggestions = []
        for item in [i for i in report.items if i.status.value == "failed"]:
            suggestions.append(f"检查并修复：{item.criterion}")
        return suggestions if suggestions else ["请检查失败的验收标准并修复"]

    def _generate_risks(self, report) -> list:
        risks = []
        error_items = [i for i in report.items if i.status.value == "error"]
        if error_items:
            risks.append(f"有 {len(error_items)} 项验证过程出错，实际通过率可能低于报告值")
        if report.pass_rate < 1.0 and report.overall_status.value == "passed":
            risks.append(f"通过率为 {report.pass_rate:.0%}，未达到 100%，存在潜在问题")
        if not report.items:
            risks.append("没有执行任何验证，结果可信度低")
        return risks


# === ConfirmationManager ===


class ConfirmationStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ISSUE_FOUND = "issue_found"
    ROLLED_BACK = "rolled_back"
    TIMEOUT = "timeout"


@dataclass
class TaskConfirmation:
    """任务确认单"""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_id: str = ""
    task_title: str = ""
    execution_result: str = ""
    step_log: list = field(default_factory=list)
    deviation_log: list = field(default_factory=list)
    verification_results: dict = field(default_factory=dict)
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    timeout_seconds: int = 3600
    user_comment: str = ""
    issue_description: str = ""
    standard_report: str = ""
    summary_review: str = ""
    standard_steps: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    confirmed_at: Optional[datetime] = None


class ConfirmationManager:
    """
    任务确认管理器

    职责：
    1. 任务执行完成后，请求用户确认
    2. 确认通过后生成标准报告和总结回顾
    3. 记录标准流程
    """

    def __init__(self, notify_fn=None, memory_manager=None):
        self.notify_fn = notify_fn
        self.memory = memory_manager
        self._pending: dict[str, TaskConfirmation] = {}
        self._history: list[TaskConfirmation] = []

    async def request_confirmation(
        self,
        task_id: str,
        task_title: str,
        execution_result: str,
        step_log: list,
        deviation_log: list = None,
        verification_results: dict = None,
        timeout_seconds: int = 3600,
    ) -> TaskConfirmation:
        """任务执行完成后，请求用户确认"""
        confirmation = TaskConfirmation(
            task_id=task_id,
            task_title=task_title,
            execution_result=execution_result,
            step_log=step_log,
            deviation_log=deviation_log or [],
            verification_results=verification_results or {},
            timeout_seconds=timeout_seconds,
        )
        self._pending[confirmation.id] = confirmation
        return confirmation

    async def handle_user_response(self, confirmation_id: str, response: str) -> TaskConfirmation:
        """处理用户确认响应"""
        confirmation = self._pending.get(confirmation_id)
        if not confirmation:
            raise ValueError(f"确认单不存在: {confirmation_id}")

        if response == "confirmed":
            confirmation.status = ConfirmationStatus.CONFIRMED
            confirmation.confirmed_at = datetime.now()
        elif response == "issue_found":
            confirmation.status = ConfirmationStatus.ISSUE_FOUND
            confirmation.issue_description = "用户发现问题，需要处理"

        self._history.append(confirmation)
        del self._pending[confirmation_id]
        return confirmation
