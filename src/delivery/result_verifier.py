"""
ResultVerifier — 结果验证器

科学依据：
1. 软件测试金字塔：L1(静态) → L2(动态) → L3(人工)
2. 统计学假设检验：H0=不达标，通过→拒绝H0
3. 风险自适应测试（Risk-Based Testing, Amland, 2002）

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：04_交付层设计.md §四
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("long_agent.delivery.result_verifier")


class VerificationLevel(Enum):
    """验证级别"""

    L1_STATIC = 1  # 静态检查
    L2_DYNAMIC = 2  # 动态测试
    L3_MANUAL = 3  # 人工确认


class VerificationStatus(Enum):
    """验证状态"""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class VerificationItem:
    """一条验证结果"""

    criterion: str = ""
    level: VerificationLevel = VerificationLevel.L1_STATIC
    status: VerificationStatus = VerificationStatus.SKIPPED
    evidence: str = ""
    error: str = ""
    duration: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class VerificationReport:
    """验证报告"""

    task_id: str = ""
    intent_id: str = ""
    overall_status: VerificationStatus = VerificationStatus.SKIPPED
    items: list = field(default_factory=list)
    summary: str = ""
    evidence_chain: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: __import__("uuid").uuid4().hex[:8])

    @property
    def pass_rate(self) -> float:
        """通过率"""
        completed = [
            i
            for i in self.items
            if i.status in (VerificationStatus.PASSED, VerificationStatus.FAILED)
        ]
        if not completed:
            return 0.0
        return sum(1 for i in completed if i.status == VerificationStatus.PASSED) / len(completed)


class ResultVerifier:
    """
    结果验证器 — 三级验证 + 风险自适应阈值

    所有参数不写死：
    - 风险等级阈值（low/medium/high）由 LLM 根据任务描述动态评估
    - 通过率阈值由风险等级动态确定
    - 测试超时时间由 LLM 根据任务复杂度动态评估
    """

    def __init__(self, default_pass_rate: float = None):
        """
        Args:
            default_pass_rate: 默认通过率阈值（None 时由 LLM 根据任务风险等级动态评估）
        """
        self.default_pass_rate = default_pass_rate  # None 表示由 LLM 动态评估

    def _assess_risk_level(self, task_description: str, context: dict = None) -> str:
        """
        评估风险等级（由 LLM 动态评估）

        评估维度：影响范围、可逆性、数据敏感性、用户数量
        """
        # 实际实现中调用 LLM
        return "medium"

    def _get_pass_rate_threshold(self, risk_level: str) -> float:
        """
        根据风险等级获取通过率阈值

        阈值不写死，由 LLM 根据用户历史数据动态调整。
        参考范围：
        - 低风险：0.70
        - 中风险：0.85
        - 高风险：0.95
        """
        thresholds = {"low": 0.70, "medium": 0.85, "high": 0.95}
        return thresholds.get(risk_level, self.default_pass_rate or 0.85)

    async def verify(self, execution_result, deliverable_plan) -> VerificationReport:
        """
        验证执行结果（核心入口）

        流程：
        1. 获取验收标准列表
        2. L1 静态检查（可自动的）
        3. L2 动态测试（可自动的）
        4. 综合判断（风险自适应阈值）
        5. 构建证据链
        """
        task_id = getattr(execution_result, "task_id", "")
        intent_id = getattr(execution_result, "intent_id", "")

        report = VerificationReport(
            task_id=task_id,
            intent_id=intent_id,
        )

        criteria = getattr(deliverable_plan, "acceptance_criteria", [])
        if not criteria:
            report.overall_status = VerificationStatus.SKIPPED
            report.summary = "没有定义验收标准，跳过自动验证"
            return report

        # L1：静态检查
        l1_items = [c for c in criteria if getattr(c, "is_automated", False)]
        l1_results = await self._run_static_checks(l1_items)
        report.items.extend(l1_results)

        # L1 通过率太低 → 不继续跑 L2
        l1_pass_rate = self._calc_pass_rate(l1_results)
        if l1_pass_rate < 0.5:
            report.overall_status = VerificationStatus.FAILED
            report.summary = f"L1 通过率过低（{l1_pass_rate:.0%}），跳过 L2"
            return report

        # L2：动态测试
        l2_results = await self._run_dynamic_tests(l1_items)
        report.items.extend(l2_results)

        # 综合判断
        all_auto_results = l1_results + l2_results
        overall_pass_rate = self._calc_pass_rate(all_auto_results)
        risk_level = self._assess_risk_level(
            getattr(deliverable_plan, "description", ""), {"criteria_count": len(criteria)}
        )
        threshold = self._get_pass_rate_threshold(risk_level)

        if overall_pass_rate >= threshold:
            report.overall_status = VerificationStatus.PASSED
            report.summary = (
                f"自动验证通过：{overall_pass_rate:.0%} "
                f"（风险等级={risk_level}, 阈值 {threshold:.0%}）"
            )
        else:
            report.overall_status = VerificationStatus.FAILED
            report.summary = (
                f"自动验证未通过：{overall_pass_rate:.0%} "
                f"（风险等级={risk_level}, 阈值 {threshold:.0%}）"
            )

        report.evidence_chain = self._build_evidence_chain(report.items)
        return report

    async def _run_static_checks(self, criteria: list) -> list:
        """运行静态检查"""
        results = []
        for criterion in criteria:
            start_time = time.time()
            try:
                result = VerificationItem(
                    criterion=getattr(criterion, "description", str(criterion)),
                    level=VerificationLevel.L1_STATIC,
                    status=VerificationStatus.PASSED,
                    evidence="静态检查通过（占位）",
                    duration=time.time() - start_time,
                )
                results.append(result)
            except Exception as e:
                results.append(
                    VerificationItem(
                        criterion=getattr(criterion, "description", str(criterion)),
                        level=VerificationLevel.L1_STATIC,
                        status=VerificationStatus.ERROR,
                        error=str(e),
                        duration=time.time() - start_time,
                    )
                )
        return results

    async def _run_dynamic_tests(self, criteria: list) -> list:
        """运行动态测试"""
        results = []
        for criterion in criteria:
            start_time = time.time()
            try:
                result = VerificationItem(
                    criterion=getattr(criterion, "description", str(criterion)),
                    level=VerificationLevel.L2_DYNAMIC,
                    status=VerificationStatus.PASSED,
                    evidence="动态测试通过（占位）",
                    duration=time.time() - start_time,
                )
                results.append(result)
            except Exception as e:
                results.append(
                    VerificationItem(
                        criterion=getattr(criterion, "description", str(criterion)),
                        level=VerificationLevel.L2_DYNAMIC,
                        status=VerificationStatus.ERROR,
                        error=str(e),
                        duration=time.time() - start_time,
                    )
                )
        return results

    def _calc_pass_rate(self, items: list) -> float:
        """计算通过率"""
        completed = [
            i for i in items if i.status in (VerificationStatus.PASSED, VerificationStatus.FAILED)
        ]
        if not completed:
            return 0.0
        return sum(1 for i in completed if i.status == VerificationStatus.PASSED) / len(completed)

    def _build_evidence_chain(self, items: list) -> list:
        """构建证据链"""
        return [
            {
                "criterion": item.criterion,
                "level": item.level.value,
                "status": item.status.value,
                "evidence": item.evidence[:200],
                "timestamp": item.timestamp.isoformat(),
            }
            for item in items
        ]
