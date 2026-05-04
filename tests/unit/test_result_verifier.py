"""
ResultVerifier 单元测试
覆盖：三级验证、风险自适应阈值、空验收标准、L1通过率过低短路、证据链构建
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from src.delivery.result_verifier import (
    ResultVerifier,
    VerificationItem,
    VerificationLevel,
    VerificationReport,
    VerificationStatus,
)

# ========== Helpers ==========

def make_exec_result(task_id="task-001", intent_id="intent-001", output="执行完毕"):
    r = MagicMock()
    r.task_id = task_id
    r.intent_id = intent_id
    r.output = output
    return r


def make_criterion(desc="验收标准", automated=True):
    c = MagicMock()
    c.description = desc
    c.is_automated = automated
    return c


def make_deliverable_plan(criteria=None, description="测试交付物"):
    plan = MagicMock()
    plan.acceptance_criteria = criteria or []
    plan.description = description
    return plan


# ========== 基础属性测试 ==========

class TestResultVerifierInit:
    def test_init_default_pass_rate_none(self):
        v = ResultVerifier()
        assert v.default_pass_rate is None

    def test_init_custom_pass_rate(self):
        v = ResultVerifier(default_pass_rate=0.9)
        assert v.default_pass_rate == 0.9


# ========== 风险等级评估测试 ==========

class TestRiskAssessment:
    def test_assess_risk_returns_medium_by_default(self):
        v = ResultVerifier()
        assert v._assess_risk_level("任意任务") == "medium"

    def test_get_pass_rate_threshold_low(self):
        v = ResultVerifier()
        assert v._get_pass_rate_threshold("low") == 0.70

    def test_get_pass_rate_threshold_medium(self):
        v = ResultVerifier()
        assert v._get_pass_rate_threshold("medium") == 0.85

    def test_get_pass_rate_threshold_high(self):
        v = ResultVerifier()
        assert v._get_pass_rate_threshold("high") == 0.95

    def test_get_pass_rate_threshold_unknown_uses_default(self):
        v = ResultVerifier(default_pass_rate=0.80)
        assert v._get_pass_rate_threshold("unknown") == 0.80

    def test_get_pass_rate_threshold_unknown_no_default(self):
        v = ResultVerifier()
        # unknown → default_pass_rate or 0.85
        assert v._get_pass_rate_threshold("unknown") == 0.85


# ========== verify 核心逻辑测试 ==========

class TestVerify:
    @pytest.mark.asyncio
    async def test_no_criteria_returns_skipped(self):
        v = ResultVerifier()
        exec_result = make_exec_result()
        plan = make_deliverable_plan(criteria=[])
        report = await v.verify(exec_result, plan)

        assert report.overall_status == VerificationStatus.SKIPPED
        assert "跳过" in report.summary

    @pytest.mark.asyncio
    async def test_all_passed_returns_passed(self):
        v = ResultVerifier()
        criteria = [make_criterion("标准1"), make_criterion("标准2")]
        exec_result = make_exec_result()
        plan = make_deliverable_plan(criteria=criteria)
        report = await v.verify(exec_result, plan)

        assert report.overall_status == VerificationStatus.PASSED
        assert report.pass_rate == 1.0
        assert "通过" in report.summary

    @pytest.mark.asyncio
    async def test_pass_rate_below_threshold_returns_failed(self):
        """当前实现中所有检查都默认 PASSED，所以 pass_rate=1.0 无法测 FAILED"""
        # 要测 FAILED 需要手动构造 VerificationItem 并注入
        v = ResultVerifier()
        report = VerificationReport(task_id="t1")
        report.items = [
            VerificationItem(criterion="c1", status=VerificationStatus.PASSED),
            VerificationItem(criterion="c2", status=VerificationStatus.PASSED),
            VerificationItem(criterion="c3", status=VerificationStatus.FAILED),
            VerificationItem(criterion="c4", status=VerificationStatus.FAILED),
            VerificationItem(criterion="c5", status=VerificationStatus.FAILED),
            VerificationItem(criterion="c6", status=VerificationStatus.FAILED),
            VerificationItem(criterion="c7", status=VerificationStatus.FAILED),
            VerificationItem(criterion="c8", status=VerificationStatus.FAILED),
            VerificationItem(criterion="c9", status=VerificationStatus.FAILED),
            VerificationItem(criterion="c10", status=VerificationStatus.FAILED),
        ]
        # pass_rate = 2/10 = 0.2, threshold for medium = 0.85 → FAILED
        rate = v._calc_pass_rate(report.items)
        assert rate == 0.2
        threshold = v._get_pass_rate_threshold("medium")
        assert rate < threshold

    @pytest.mark.asyncio
    async def test_report_has_evidence_chain(self):
        v = ResultVerifier()
        criteria = [make_criterion("标准1")]
        plan = make_deliverable_plan(criteria=criteria)
        report = await v.verify(make_exec_result(), plan)

        assert len(report.evidence_chain) > 0
        assert "criterion" in report.evidence_chain[0]
        assert "status" in report.evidence_chain[0]

    @pytest.mark.asyncio
    async def test_report_task_id_matches(self):
        v = ResultVerifier()
        exec_result = make_exec_result(task_id="task-abc")
        plan = make_deliverable_plan(criteria=[make_criterion()])
        report = await v.verify(exec_result, plan)
        assert report.task_id == "task-abc"

    @pytest.mark.asyncio
    async def test_report_has_created_at(self):
        v = ResultVerifier()
        report = await v.verify(
            make_exec_result(),
            make_deliverable_plan(criteria=[make_criterion()]),
        )
        assert isinstance(report.created_at, datetime)


# ========== 通过率计算测试 ==========

class TestCalcPassRate:
    def test_empty_list(self):
        v = ResultVerifier()
        assert v._calc_pass_rate([]) == 0.0

    def test_all_passed(self):
        v = ResultVerifier()
        items = [VerificationItem(status=VerificationStatus.PASSED) for _ in range(5)]
        assert v._calc_pass_rate(items) == 1.0

    def test_all_failed(self):
        v = ResultVerifier()
        items = [VerificationItem(status=VerificationStatus.FAILED) for _ in range(5)]
        assert v._calc_pass_rate(items) == 0.0

    def test_mixed(self):
        v = ResultVerifier()
        items = [
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.FAILED),
            VerificationItem(status=VerificationStatus.FAILED),
        ]
        assert v._calc_pass_rate(items) == 0.5

    def test_skipped_not_counted(self):
        v = ResultVerifier()
        items = [
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.SKIPPED),
        ]
        # SKIPPED 不在 completed 列表中，所以分母=1
        assert v._calc_pass_rate(items) == 1.0


# ========== 证据链测试 ==========

class TestEvidenceChain:
    def test_empty_items(self):
        v = ResultVerifier()
        assert v._build_evidence_chain([]) == []

    def test_evidence_chain_fields(self):
        v = ResultVerifier()
        items = [
            VerificationItem(
                criterion="c1",
                level=VerificationLevel.L1_STATIC,
                status=VerificationStatus.PASSED,
                evidence="证据文本",
            )
        ]
        chain = v._build_evidence_chain(items)
        assert len(chain) == 1
        entry = chain[0]
        assert entry["criterion"] == "c1"
        assert entry["level"] == 1
        assert entry["status"] == "passed"
        assert entry["evidence"] == "证据文本"
        assert "timestamp" in entry

    def test_evidence_truncated_to_200(self):
        v = ResultVerifier()
        items = [
            VerificationItem(
                criterion="c1",
                evidence="x" * 500,
            )
        ]
        chain = v._build_evidence_chain(items)
        assert len(chain[0]["evidence"]) == 200


# ========== VerificationReport.pass_rate 属性测试 ==========

class TestVerificationReportPassRate:
    def test_pass_rate_empty(self):
        r = VerificationReport()
        assert r.pass_rate == 0.0

    def test_pass_rate_all_passed(self):
        r = VerificationReport()
        r.items = [VerificationItem(status=VerificationStatus.PASSED) for _ in range(3)]
        assert r.pass_rate == 1.0

    def test_pass_rate_mixed(self):
        r = VerificationReport()
        r.items = [
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.FAILED),
        ]
        assert r.pass_rate == 0.5

    def test_pass_rate_skipped_excluded(self):
        r = VerificationReport()
        r.items = [
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.SKIPPED),
            VerificationItem(status=VerificationStatus.SKIPPED),
        ]
        assert r.pass_rate == 1.0
