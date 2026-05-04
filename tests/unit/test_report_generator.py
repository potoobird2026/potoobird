"""
ReportGenerator 单元测试
覆盖：报告生成、结论映射、分层摘要、建议生成、风险评估、技术详情
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from src.delivery.report_generator import (
    ReportGenerator, DeliveryReport,
    ConfirmationManager, TaskConfirmation, ConfirmationStatus,
)
from src.delivery.result_verifier import (
    VerificationReport, VerificationItem,
    VerificationLevel, VerificationStatus,
)


# ========== Helpers ==========

def make_verification_report(
    task_id="task-001",
    overall_status=VerificationStatus.PASSED,
    items=None,
):
    r = VerificationReport(task_id=task_id)
    r.overall_status = overall_status
    r.items = items or []
    r.evidence_chain = []
    return r


def make_item(desc="验收标准", status=VerificationStatus.PASSED,
              level=VerificationLevel.L1_STATIC, evidence="ok", error="",
              duration=0.5):
    return VerificationItem(
        criterion=desc, level=level, status=status,
        evidence=evidence, error=error, duration=duration,
    )


# ========== ReportGenerator.generate 测试 ==========

class TestGenerate:
    def test_generate_returns_delivery_report(self):
        gen = ReportGenerator()
        report = make_verification_report()
        result = gen.generate(report)
        assert isinstance(result, DeliveryReport)

    def test_generate_task_id_preserved(self):
        gen = ReportGenerator()
        report = make_verification_report(task_id="t-123")
        result = gen.generate(report)
        assert result.task_id == "t-123"

    def test_generate_has_conclusion(self):
        gen = ReportGenerator()
        result = gen.generate(make_verification_report())
        assert len(result.conclusion) > 0

    def test_generate_has_summary(self):
        gen = ReportGenerator()
        result = gen.generate(make_verification_report())
        assert len(result.summary) > 0

    def test_generate_has_details(self):
        gen = ReportGenerator()
        items = [make_item("标准1"), make_item("标准2")]
        report = make_verification_report(items=items)
        result = gen.generate(report)
        assert len(result.details) == 2

    def test_generate_evidence_chain_preserved(self):
        gen = ReportGenerator()
        report = make_verification_report()
        report.evidence_chain = [{"criterion": "c1", "status": "passed"}]
        result = gen.generate(report)
        assert len(result.evidence_chain) == 1


# ========== 结论生成测试 ==========

class TestGenerateConclusion:
    def test_conclusion_passed(self):
        gen = ReportGenerator()
        result = gen._generate_conclusion(
            make_verification_report(overall_status=VerificationStatus.PASSED)
        )
        assert "✅" in result or "完成" in result

    def test_conclusion_failed(self):
        gen = ReportGenerator()
        result = gen._generate_conclusion(
            make_verification_report(overall_status=VerificationStatus.FAILED)
        )
        assert "❌" in result or "未完成" in result

    def test_conclusion_error(self):
        gen = ReportGenerator()
        result = gen._generate_conclusion(
            make_verification_report(overall_status=VerificationStatus.ERROR)
        )
        assert "⚠️" in result or "出错" in result

    def test_conclusion_skipped(self):
        gen = ReportGenerator()
        result = gen._generate_conclusion(
            make_verification_report(overall_status=VerificationStatus.SKIPPED)
        )
        assert "⏭️" in result or "跳过" in result

    def test_conclusion_includes_pass_rate(self):
        gen = ReportGenerator()
        items = [
            make_item(status=VerificationStatus.PASSED),
            make_item(status=VerificationStatus.FAILED),
        ]
        report = make_verification_report(items=items)
        result = gen._generate_conclusion(report)
        assert "50%" in result

    def test_conclusion_empty_items_no_pass_rate(self):
        gen = ReportGenerator()
        report = make_verification_report(items=[])
        result = gen._generate_conclusion(report)
        # 没有 items 时不追加通过率
        assert "%" not in result or "0%" in result


# ========== Summary 生成测试 ==========

class TestGenerateSummary:
    def test_summary_all_passed(self):
        gen = ReportGenerator()
        items = [make_item(status=VerificationStatus.PASSED) for _ in range(3)]
        report = make_verification_report(
            overall_status=VerificationStatus.PASSED, items=items
        )
        result = gen._generate_summary(report)
        assert "3 项通过" in result
        assert "可以正常使用" in result

    def test_summary_with_failures(self):
        gen = ReportGenerator()
        items = [
            make_item("标准1", VerificationStatus.PASSED),
            make_item("标准2", VerificationStatus.FAILED),
            make_item("标准3", VerificationStatus.FAILED),
        ]
        report = make_verification_report(
            overall_status=VerificationStatus.FAILED, items=items
        )
        result = gen._generate_summary(report)
        assert "2 项失败" in result
        assert "未通过" in result

    def test_summary_counts_errors(self):
        gen = ReportGenerator()
        items = [
            make_item("s1", VerificationStatus.PASSED),
            make_item("s2", VerificationStatus.ERROR),
        ]
        report = make_verification_report(items=items)
        result = gen._generate_summary(report)
        assert "1 项出错" in result


# ========== Details 生成测试 ==========

class TestGenerateDetails:
    def test_details_format(self):
        gen = ReportGenerator()
        items = [make_item("标准1", VerificationStatus.PASSED)]
        report = make_verification_report(items=items)
        details = gen._generate_details(report)
        assert len(details) == 1
        assert "status" in details[0]
        assert "criterion" in details[0]
        assert "evidence" in details[0]
        assert "duration" in details[0]

    def test_details_status_icons(self):
        gen = ReportGenerator()
        items = [
            make_item("p", VerificationStatus.PASSED),
            make_item("f", VerificationStatus.FAILED),
            make_item("e", VerificationStatus.ERROR),
            make_item("s", VerificationStatus.SKIPPED),
        ]
        report = make_verification_report(items=items)
        details = gen._generate_details(report)
        icons = [d["status"] for d in details]
        assert any("✅" in i for i in icons)
        assert any("❌" in i for i in icons)
        assert any("⚠️" in i for i in icons)
        assert any("⏭️" in i for i in icons)

    def test_details_evidence_truncated(self):
        gen = ReportGenerator()
        items = [make_item(evidence="x" * 200)]
        report = make_verification_report(items=items)
        details = gen._generate_details(report)
        assert len(details[0]["evidence"]) <= 100


# ========== Suggestions 生成测试 ==========

class TestGenerateSuggestions:
    def test_suggestions_when_passed(self):
        gen = ReportGenerator()
        report = make_verification_report(overall_status=VerificationStatus.PASSED)
        suggestions = gen._generate_suggestions(report)
        assert len(suggestions) > 0
        assert any("保存" in s or "无需改进" in s for s in suggestions)

    def test_suggestions_when_failed(self):
        gen = ReportGenerator()
        items = [make_item("登录功能", VerificationStatus.FAILED)]
        report = make_verification_report(
            overall_status=VerificationStatus.FAILED, items=items
        )
        suggestions = gen._generate_suggestions(report)
        assert any("登录功能" in s for s in suggestions)

    def test_suggestions_empty_when_no_failures(self):
        gen = ReportGenerator()
        report = make_verification_report(overall_status=VerificationStatus.PASSED, items=[])
        suggestions = gen._generate_suggestions(report)
        assert len(suggestions) > 0


# ========== Risks 生成测试 ==========

class TestGenerateRisks:
    def test_risks_when_errors_exist(self):
        gen = ReportGenerator()
        items = [make_item("e1", VerificationStatus.ERROR)]
        report = make_verification_report(items=items)
        risks = gen._generate_risks(report)
        assert any("出错" in r for r in risks)

    def test_risks_when_partial_pass(self):
        gen = ReportGenerator()
        items = [
            make_item("s1", VerificationStatus.PASSED),
            make_item("s2", VerificationStatus.FAILED),
        ]
        report = make_verification_report(
            overall_status=VerificationStatus.PASSED, items=items
        )
        risks = gen._generate_risks(report)
        assert any("100%" in r or "潜在" in r for r in risks)

    def test_risks_when_no_items(self):
        gen = ReportGenerator()
        report = make_verification_report(items=[])
        risks = gen._generate_risks(report)
        assert any("没有执行" in r or "可信度" in r for r in risks)


# ========== 分层摘要测试 ==========

class TestLayeredSummary:
    def test_user_summary_fields(self):
        gen = ReportGenerator()
        items = [
            make_item("s1", VerificationStatus.PASSED, duration=1.0),
            make_item("s2", VerificationStatus.FAILED, duration=2.0),
        ]
        report = make_verification_report(items=items)
        summary = gen._build_user_summary(report, "结论")
        assert summary["conclusion"] == "结论"
        assert summary["total_items"] == 2
        assert summary["passed_items"] == 1
        assert summary["failed_items"] == 1
        assert "total_duration" in summary

    def test_tech_detail_has_levels(self):
        gen = ReportGenerator()
        items = [
            make_item("l1", level=VerificationLevel.L1_STATIC),
            make_item("l2", level=VerificationLevel.L2_DYNAMIC),
        ]
        report = make_verification_report(items=items)
        detail = gen._build_tech_detail(report, [], [], [])
        assert "l1_static" in detail
        assert "l2_dynamic" in detail
        assert "l3_manual" in detail

    def test_level_pass_rate_na_when_empty(self):
        gen = ReportGenerator()
        assert gen._level_pass_rate([]) == "N/A"

    def test_level_pass_rate_calculation(self):
        gen = ReportGenerator()
        items = [
            make_item(status=VerificationStatus.PASSED),
            make_item(status=VerificationStatus.FAILED),
        ]
        assert gen._level_pass_rate(items) == "50%"


# ========== ConfirmationManager 测试 ==========

class TestConfirmationManager:
    def test_init(self):
        mgr = ConfirmationManager()
        assert mgr._pending == {}
        assert mgr._history == []

    @pytest.mark.asyncio
    async def test_request_confirmation(self):
        mgr = ConfirmationManager()
        c = await mgr.request_confirmation("t1", "任务标题", "执行结果", [])
        assert c.task_id == "t1"
        assert c.task_title == "任务标题"
        assert c.status == ConfirmationStatus.PENDING
        assert c.id in mgr._pending

    @pytest.mark.asyncio
    async def test_handle_confirmed(self):
        mgr = ConfirmationManager()
        c = await mgr.request_confirmation("t1", "任务", "结果", [])
        result = await mgr.handle_user_response(c.id, "confirmed")
        assert result.status == ConfirmationStatus.CONFIRMED
        assert result.confirmed_at is not None
        assert c.id not in mgr._pending
        assert len(mgr._history) == 1

    @pytest.mark.asyncio
    async def test_handle_issue_found(self):
        mgr = ConfirmationManager()
        c = await mgr.request_confirmation("t1", "任务", "结果", [])
        result = await mgr.handle_user_response(c.id, "issue_found")
        assert result.status == ConfirmationStatus.ISSUE_FOUND
        assert "发现问题" in result.issue_description

    @pytest.mark.asyncio
    async def test_handle_invalid_id_raises(self):
        mgr = ConfirmationManager()
        with pytest.raises(ValueError, match="确认单不存在"):
            await mgr.handle_user_response("nonexistent", "confirmed")

    @pytest.mark.asyncio
    async def test_deviation_log_optional(self):
        mgr = ConfirmationManager()
        c = await mgr.request_confirmation("t1", "任务", "结果", [], deviation_log=[{"step": 1}])
        assert len(c.deviation_log) == 1

    @pytest.mark.asyncio
    async def test_verification_results_optional(self):
        mgr = ConfirmationManager()
        c = await mgr.request_confirmation("t1", "任务", "结果", [], verification_results={"pass": True})
        assert c.verification_results["pass"] is True
