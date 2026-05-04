"""
SecurityGuard 审批模块和冲突检测器补充测试
提升 src/security/guard.py 覆盖率

覆盖：
- ApprovalModule 完整功能
- ConflictChecker 完整功能
- ApprovalRequest 数据类
"""

import pytest

from src.security.guard import (
    ApprovalModule,
    ApprovalRequest,
    ApprovalStatus,
    Conflict,
    ConflictChecker,
    ConflictType,
)


class TestApprovalModule:
    """审批模块测试"""

    def test_init_default_timeout(self):
        """默认基础超时"""
        mod = ApprovalModule()
        assert mod.base_timeout == 3600.0

    def test_init_custom_timeout(self):
        """自定义基础超时"""
        mod = ApprovalModule(base_timeout=1800.0)
        assert mod.base_timeout == 1800.0

    def test_evaluate_risk_known_actions(self):
        """已知操作风险评分"""
        mod = ApprovalModule()
        assert mod.evaluate_risk("memory_write") == 0.3
        assert mod.evaluate_risk("personality_update") == 0.6
        assert mod.evaluate_risk("clear_memory") == 0.8
        assert mod.evaluate_risk("reset_personality") == 0.9
        assert mod.evaluate_risk("tool_call") == 0.4
        assert mod.evaluate_risk("file_delete") == 0.7
        assert mod.evaluate_risk("system_config") == 0.8

    def test_evaluate_risk_unknown_action(self):
        """未知操作默认风险"""
        mod = ApprovalModule()
        assert mod.evaluate_risk("unknown_action") == 0.5

    def test_calculate_timeout_basic(self):
        """基本超时计算"""
        mod = ApprovalModule(base_timeout=3600.0)
        timeout = mod.calculate_timeout(risk_score=0.5, urgency_score=0.5)
        assert timeout == 3600.0 * 1.5 / 1.5  # = 3600

    def test_calculate_timeout_high_risk(self):
        """高风险操作超时更长"""
        mod = ApprovalModule(base_timeout=3600.0)
        timeout = mod.calculate_timeout(risk_score=0.9, urgency_score=0.1)
        assert timeout > 3600.0

    def test_calculate_timeout_high_urgency(self):
        """高紧急度操作超时更短"""
        mod = ApprovalModule(base_timeout=3600.0)
        timeout = mod.calculate_timeout(risk_score=0.1, urgency_score=0.9)
        assert timeout < 3600.0

    def test_calculate_timeout_min_bound(self):
        """超时应不小于60秒"""
        mod = ApprovalModule(base_timeout=10.0)
        timeout = mod.calculate_timeout(risk_score=0.0, urgency_score=1.0)
        assert timeout >= 60.0

    def test_calculate_timeout_max_bound(self):
        """超时应不大于7200秒"""
        mod = ApprovalModule(base_timeout=10000.0)
        timeout = mod.calculate_timeout(risk_score=1.0, urgency_score=0.0)
        assert timeout <= 7200.0

    @pytest.mark.asyncio
    async def test_request_approval(self):
        """创建审批请求"""
        mod = ApprovalModule()
        req = await mod.request_approval("memory_write", {"key": "value"})
        assert isinstance(req, ApprovalRequest)
        assert req.action == "memory_write"
        assert req.params == {"key": "value"}
        assert req.status == ApprovalStatus.PENDING
        assert req.id in mod._pending

    @pytest.mark.asyncio
    async def test_request_approval_with_urgency(self):
        """创建紧急审批请求"""
        mod = ApprovalModule()
        req = await mod.request_approval("clear_memory", urgency_score=0.9)
        assert req.urgency_score == 0.9
        assert req.risk_score == 0.8

    @pytest.mark.asyncio
    async def test_request_approval_default_params(self):
        """默认参数"""
        mod = ApprovalModule()
        req = await mod.request_approval("tool_call")
        assert req.params == {}

    @pytest.mark.asyncio
    async def test_approve(self):
        """批准请求"""
        mod = ApprovalModule()
        req = await mod.request_approval("memory_write")
        result = mod.approve(req.id, approver="test_user", reason="OK")
        assert result.status == ApprovalStatus.APPROVED
        assert result.approver == "test_user"
        assert result.reason == "OK"
        assert result.resolved_at is not None

    @pytest.mark.asyncio
    async def test_approve_nonexistent_raises(self):
        """批准不存在的请求应抛出异常"""
        mod = ApprovalModule()
        with pytest.raises(ValueError):
            mod.approve("nonexistent-id")

    @pytest.mark.asyncio
    async def test_reject(self):
        """拒绝请求"""
        mod = ApprovalModule()
        req = await mod.request_approval("clear_memory")
        result = mod.reject(req.id, approver="test_user", reason="太危险")
        assert result.status == ApprovalStatus.REJECTED
        assert result.approver == "test_user"

    @pytest.mark.asyncio
    async def test_reject_nonexistent_raises(self):
        """拒绝不存在的请求应抛出异常"""
        mod = ApprovalModule()
        with pytest.raises(ValueError):
            mod.reject("nonexistent-id")

    @pytest.mark.asyncio
    async def test_pending_count(self):
        """待审批数量"""
        mod = ApprovalModule()
        assert mod.pending_count == 0
        await mod.request_approval("memory_write")
        assert mod.pending_count == 1

    @pytest.mark.asyncio
    async def test_history_after_approve(self):
        """批准后历史记录"""
        mod = ApprovalModule()
        req = await mod.request_approval("memory_write")
        mod.approve(req.id)
        assert len(mod.history) == 1

    @pytest.mark.asyncio
    async def test_pending_removed_after_approve(self):
        """批准后从待审批中移除"""
        mod = ApprovalModule()
        req = await mod.request_approval("memory_write")
        mod.approve(req.id)
        assert mod.pending_count == 0


class TestApprovalRequest:
    """审批请求数据类测试"""

    def test_default_values(self):
        """默认值"""
        req = ApprovalRequest()
        assert req.action == ""
        assert req.params == {}
        assert req.risk_score == 0.0
        assert req.urgency_score == 0.5
        assert req.status == ApprovalStatus.PENDING
        assert req.timeout_seconds == 3600.0
        assert req.resolved_at is None
        assert req.approver == ""
        assert req.reason == ""
        assert req.id != ""

    def test_custom_values(self):
        """自定义值"""
        req = ApprovalRequest(
            action="test",
            params={"key": "value"},
            risk_score=0.5,
        )
        assert req.action == "test"
        assert req.risk_score == 0.5


class TestApprovalStatus:
    """审批状态枚举测试"""

    def test_all_statuses(self):
        """所有状态"""
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.TIMEOUT.value == "timeout"
        assert ApprovalStatus.CANCELLED.value == "cancelled"


class TestConflictChecker:
    """冲突检测器测试"""

    def test_init_default_threshold(self):
        """默认 Jaccard 阈值"""
        checker = ConflictChecker()
        assert checker.jaccard_threshold == 0.3

    def test_init_custom_threshold(self):
        """自定义 Jaccard 阈值"""
        checker = ConflictChecker(jaccard_threshold=0.5)
        assert checker.jaccard_threshold == 0.5

    def test_check_no_conflicts(self):
        """无冲突"""
        checker = ConflictChecker()
        conflicts = checker.check("用户喜欢红色", ["今天天气很好", "Python 是编程语言"])
        assert len(conflicts) == 0

    def test_check_with_similar_content(self):
        """相似内容检测"""
        checker = ConflictChecker()
        # 相似内容但无矛盾
        conflicts = checker.check(
            "用户喜欢红色",
            ["用户喜欢红色因为很醒目"]
        )
        # 相似度高但无矛盾词
        assert isinstance(conflicts, list)

    def test_check_empty_existing(self):
        """空现有知识列表"""
        checker = ConflictChecker()
        conflicts = checker.check("新知识", [])
        assert len(conflicts) == 0

    def test_jaccard_similarity(self):
        """Jaccard 相似度计算"""
        checker = ConflictChecker()
        # 完全相同的文本
        sim = checker._jaccard_similarity("abc", "abc")
        assert sim == 1.0

    def test_jaccard_similarity_no_overlap(self):
        """无重叠文本"""
        checker = ConflictChecker()
        sim = checker._jaccard_similarity("abc", "xyz")
        assert sim == 0.0

    def test_jaccard_similarity_partial(self):
        """部分重叠"""
        checker = ConflictChecker()
        sim = checker._jaccard_similarity("abc de", "abc fg")
        assert 0.0 < sim < 1.0


class TestConflict:
    """冲突数据类测试"""

    def test_default_values(self):
        """默认值"""
        c = Conflict()
        assert c.new_knowledge == ""
        assert c.existing_knowledge == ""
        assert c.conflict_type == ConflictType.NONE
        assert c.confidence == 0.0
        assert c.description == ""

    def test_custom_values(self):
        """自定义值"""
        c = Conflict(
            new_knowledge="A",
            existing_knowledge="B",
            conflict_type=ConflictType.DIRECT,
            confidence=0.9,
            description="直接矛盾",
        )
        assert c.conflict_type == ConflictType.DIRECT
        assert c.confidence == 0.9


class TestConflictType:
    """冲突类型枚举"""

    def test_all_types(self):
        """所有类型"""
        assert ConflictType.DIRECT.value == "direct"
        assert ConflictType.POTENTIAL.value == "potential"
        assert ConflictType.NONE.value == "none"
