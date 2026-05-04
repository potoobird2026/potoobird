"""交付层单元测试"""

from unittest.mock import MagicMock

import pytest


class TestResultVerifier:
    def test_init_default(self):
        """默认初始化"""
        from src.delivery.result_verifier import ResultVerifier
        v = ResultVerifier()
        assert v.default_pass_rate is None

    def test_init_custom(self):
        """自定义通过率"""
        from src.delivery.result_verifier import ResultVerifier
        v = ResultVerifier(default_pass_rate=0.85)
        assert v.default_pass_rate == 0.85

    def test_assess_risk_level(self):
        """风险评估"""
        from src.delivery.result_verifier import ResultVerifier
        v = ResultVerifier()
        risk = v._assess_risk_level("简单查询")
        assert risk in ("low", "medium", "high")

    @pytest.mark.asyncio
    async def test_verify_empty_criteria(self):
        """空验收标准"""
        from src.delivery.result_verifier import ResultVerifier, VerificationReport
        v = ResultVerifier()
        exec_result = MagicMock()
        exec_result.steps = []
        plan = MagicMock()
        plan.verification_criteria = []
        report = await v.verify(exec_result, plan)
        assert isinstance(report, VerificationReport)
        assert len(report.items) == 0

    @pytest.mark.asyncio
    async def test_verify_with_criteria(self):
        """有验收标准"""
        from src.delivery.result_verifier import ResultVerifier, VerificationReport
        v = ResultVerifier()
        exec_result = MagicMock()
        exec_result.steps = [MagicMock()]
        plan = MagicMock()
        plan.verification_criteria = [{"check": "输出不为空", "type": "static"}]
        report = await v.verify(exec_result, plan)
        assert isinstance(report, VerificationReport)

    def test_calc_pass_rate(self):
        """计算通过率"""
        from src.delivery.result_verifier import (
            ResultVerifier,
            VerificationItem,
            VerificationStatus,
        )
        v = ResultVerifier()
        items = [
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.FAILED),
        ]
        rate = v._calc_pass_rate(items)
        assert rate == pytest.approx(2 / 3)

    def test_pass_rate_empty(self):
        """空列表通过率为0"""
        from src.delivery.result_verifier import ResultVerifier
        v = ResultVerifier()
        assert v._calc_pass_rate([]) == 0.0

    def test_verification_report_pass_rate(self):
        """验证报告通过率"""
        from src.delivery.result_verifier import (
            VerificationItem,
            VerificationReport,
            VerificationStatus,
        )
        report = VerificationReport()
        assert report.pass_rate == 0.0
        report.items = [
            VerificationItem(status=VerificationStatus.PASSED),
            VerificationItem(status=VerificationStatus.PASSED),
        ]
        assert report.pass_rate == 1.0


class TestReportGenerator:
    def test_init(self):
        """初始化"""
        from src.delivery.report_generator import ReportGenerator
        gen = ReportGenerator()
        assert isinstance(gen, ReportGenerator)

    def test_generate(self):
        """生成报告"""
        from src.delivery.report_generator import ReportGenerator
        from src.delivery.result_verifier import VerificationReport
        gen = ReportGenerator()
        report = VerificationReport()
        result = gen.generate(report)
        assert result is not None
        assert hasattr(result, "conclusion")
        assert hasattr(result, "summary")


class TestConfirmationManager:
    def test_init(self):
        """初始化"""
        from src.delivery.report_generator import ConfirmationManager
        mgr = ConfirmationManager()
        assert isinstance(mgr, ConfirmationManager)
        assert len(mgr._pending) == 0

    @pytest.mark.asyncio
    async def test_request_confirmation(self):
        """请求确认"""
        from src.delivery.report_generator import ConfirmationManager, ConfirmationStatus
        mgr = ConfirmationManager()
        confirmation = await mgr.request_confirmation(
            task_id="task-1",
            task_title="测试任务",
            execution_result="执行完成",
            step_log=[{"step": 1, "description": "步骤1"}],
        )
        assert confirmation.id is not None
        assert confirmation.status == ConfirmationStatus.PENDING

    @pytest.mark.asyncio
    async def test_handle_user_response_confirmed(self):
        """用户确认"""
        from src.delivery.report_generator import ConfirmationManager, ConfirmationStatus
        mgr = ConfirmationManager()
        confirmation = await mgr.request_confirmation(
            task_id="task-1",
            task_title="测试任务",
            execution_result="执行完成",
            step_log=[],
        )
        result = await mgr.handle_user_response(confirmation.id, "confirmed")
        assert result.status == ConfirmationStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_handle_user_response_issue(self):
        """用户发现问题"""
        from src.delivery.report_generator import ConfirmationManager, ConfirmationStatus
        mgr = ConfirmationManager()
        confirmation = await mgr.request_confirmation(
            task_id="task-1",
            task_title="测试任务",
            execution_result="执行完成",
            step_log=[],
        )
        result = await mgr.handle_user_response(confirmation.id, "issue_found")
        assert result.status == ConfirmationStatus.ISSUE_FOUND
