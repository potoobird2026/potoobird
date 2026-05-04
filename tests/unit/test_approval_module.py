"""
单元测试 — 审批模块 (src/security/guard.py - ApprovalModule)

覆盖：
- ApprovalModule 初始化
- evaluate_risk() - 风险评估
- calculate_timeout() - 自适应超时
- request_approval() - 审批请求
"""

import pytest
from src.security.guard import ApprovalModule, ApprovalRequest, ApprovalStatus


class TestApprovalModuleInit:
    def test_default_timeout(self):
        am = ApprovalModule()
        assert am.base_timeout == 3600.0

    def test_custom_timeout(self):
        am = ApprovalModule(base_timeout=1800.0)
        assert am.base_timeout == 1800.0

    def test_none_timeout_uses_default(self):
        am = ApprovalModule(base_timeout=None)
        assert am.base_timeout == 3600.0

    def test_empty_pending_and_history(self):
        am = ApprovalModule()
        assert am._pending == {}
        assert am._history == []


class TestEvaluateRisk:
    def test_memory_write_risk(self):
        am = ApprovalModule()
        assert am.evaluate_risk("memory_write") == 0.3

    def test_personality_update_risk(self):
        am = ApprovalModule()
        assert am.evaluate_risk("personality_update") == 0.6

    def test_clear_memory_risk(self):
        am = ApprovalModule()
        assert am.evaluate_risk("clear_memory") == 0.8

    def test_reset_personality_risk(self):
        am = ApprovalModule()
        assert am.evaluate_risk("reset_personality") == 0.9

    def test_tool_call_risk(self):
        am = ApprovalModule()
        assert am.evaluate_risk("tool_call") == 0.4

    def test_file_delete_risk(self):
        am = ApprovalModule()
        assert am.evaluate_risk("file_delete") == 0.7

    def test_system_config_risk(self):
        am = ApprovalModule()
        assert am.evaluate_risk("system_config") == 0.8

    def test_unknown_action_default(self):
        am = ApprovalModule()
        assert am.evaluate_risk("unknown_action") == 0.5

    def test_risk_with_params(self):
        am = ApprovalModule()
        # Params don't change the result in current implementation
        assert am.evaluate_risk("memory_write", {"key": "val"}) == 0.3


class TestCalculateTimeout:
    def test_low_risk_low_urgency(self):
        am = ApprovalModule(base_timeout=3600)
        timeout = am.calculate_timeout(0.1, 0.9)
        assert timeout > 0
        assert timeout <= 7200

    def test_high_risk_high_urgency(self):
        am = ApprovalModule(base_timeout=3600)
        timeout = am.calculate_timeout(0.9, 0.9)
        assert timeout > 0

    def test_high_risk_low_urgency(self):
        """高风险 + 低紧急 = 最长超时"""
        am = ApprovalModule(base_timeout=3600)
        timeout = am.calculate_timeout(0.9, 0.1)
        assert timeout > 3600  # 应该比基础超时更长

    def test_low_risk_high_urgency(self):
        """低风险 + 高紧急 = 最短超时"""
        am = ApprovalModule(base_timeout=3600)
        timeout = am.calculate_timeout(0.1, 0.9)
        assert timeout < 3600  # 应该比基础超时更短

    def test_minimum_timeout(self):
        """超时最短 60 秒"""
        am = ApprovalModule(base_timeout=100)
        timeout = am.calculate_timeout(0.0, 1.0)
        assert timeout >= 60.0

    def test_maximum_timeout(self):
        """超时最长 7200 秒"""
        am = ApprovalModule(base_timeout=100000)
        timeout = am.calculate_timeout(1.0, 0.0)
        assert timeout <= 7200.0

    def test_default_urgency(self):
        am = ApprovalModule(base_timeout=3600)
        timeout = am.calculate_timeout(0.5)
        assert 60.0 <= timeout <= 7200.0


class TestRequestApproval:
    @pytest.mark.asyncio
    async def test_creates_request(self):
        am = ApprovalModule()
        req = await am.request_approval("memory_write")
        assert req is not None
        assert req.action == "memory_write"
        assert req.id in am._pending

    @pytest.mark.asyncio
    async def test_request_has_risk_score(self):
        am = ApprovalModule()
        req = await am.request_approval("memory_write")
        assert req.risk_score == 0.3

    @pytest.mark.asyncio
    async def test_request_has_timeout(self):
        am = ApprovalModule()
        req = await am.request_approval("memory_write")
        assert req.timeout_seconds > 0

    @pytest.mark.asyncio
    async def test_pending_stored(self):
        am = ApprovalModule()
        req = await am.request_approval("clear_memory")
        assert len(am._pending) == 1
        assert am._pending[req.id] is req

    @pytest.mark.asyncio
    async def test_multiple_requests(self):
        am = ApprovalModule()
        req1 = await am.request_approval("memory_write")
        req2 = await am.request_approval("clear_memory")
        assert len(am._pending) == 2
        assert req1.id != req2.id


class TestApprovalRequest:
    def test_defaults(self):
        req = ApprovalRequest()
        assert req.action == ""
        assert req.params == {}
        assert req.risk_score == 0.0
        assert req.urgency_score == 0.5
        assert req.status == ApprovalStatus.PENDING
