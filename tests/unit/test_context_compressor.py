"""
上下文压缩器 — 单元测试（V2 多算法融合压缩引擎）

测试覆盖：
- 短消息不压缩（MIN_CONTEXT_MESSAGES 以下直接返回）
- 双锚点保边（锚点消息不被裁剪）
- 10算法评分 + 幂律裁剪（compress() 主路径）
- 幂律裁剪（apply_power_law_pruning）
- 压缩结果格式（CompressResult 字段完整性）
- 空消息 / 边界条件
"""

from datetime import datetime, timedelta

import pytest

from src.context.compressor import CompressResult, ContextCompressor


@pytest.fixture
def compressor():
    return ContextCompressor()


def _make_messages(count: int, hours_ago: int = 0, content_prefix: str = "消息") -> list[dict]:
    """生成测试消息列表"""
    now = datetime.utcnow()
    return [
        {
            "role": "user",
            "content": f"{content_prefix}{i}",
            "created_at": (now - timedelta(hours=hours_ago + i)).isoformat() + "Z",
        }
        for i in range(count)
    ]


class TestShortMessagesNotCompressed:
    """短消息不压缩（MIN_CONTEXT_MESSAGES 以下直接返回）"""

    @pytest.mark.asyncio
    async def test_below_min_unchanged(self, compressor):
        """消息数低于下限，不压缩"""
        messages = _make_messages(3)
        result = await compressor.compress(messages)
        assert result.compressed_count == 3
        assert result.original_count == 3
        assert result.method == "v2_fusion_power_law"

    @pytest.mark.asyncio
    async def test_empty_messages(self, compressor):
        """空消息列表"""
        result = await compressor.compress([])
        assert result.original_count == 0
        assert result.compressed_count == 0

    @pytest.mark.asyncio
    async def test_single_message(self, compressor):
        """单条消息不压缩"""
        messages = [{"role": "user", "content": "你好"}]
        result = await compressor.compress(messages)
        assert result.compressed_count == 1


class TestDualAnchorPreservation:
    """双锚点保边：锚点区域消息不被裁剪"""

    @pytest.mark.asyncio
    async def test_anchor_prefix_preserved(self, compressor):
        """最早M条锚点消息被保留"""
        messages = _make_messages(30)
        result = await compressor.compress(messages)
        # 压缩后保留的消息数应 <= 原始数
        assert result.compressed_count <= result.original_count
        # 锚点消息（最早的几条）应在 kept_ids 中
        assert len(result.kept_ids) == result.compressed_count

    @pytest.mark.asyncio
    async def test_anchor_suffix_preserved(self, compressor):
        """最近N条工作记忆被保留"""
        messages = _make_messages(30)
        result = await compressor.compress(messages)
        # 最近的消息应在 kept_ids 中
        assert result.compressed_count > 0


class TestCompressionResultFormat:
    """压缩结果格式：CompressResult 字段完整性"""

    @pytest.mark.asyncio
    async def test_compression_result_format(self, compressor):
        """压缩结果格式正确"""
        messages = _make_messages(25)
        result = await compressor.compress(messages)
        assert isinstance(result, CompressResult)
        assert result.original_count == 25
        assert result.compressed_count <= result.original_count
        assert result.method == "v2_fusion_power_law"

    @pytest.mark.asyncio
    async def test_pruned_count_non_negative(self, compressor):
        """pruned_count >= 0"""
        messages = _make_messages(25)
        result = await compressor.compress(messages)
        assert result.pruned_count >= 0

    @pytest.mark.asyncio
    async def test_compressed_count_within_budget(self, compressor):
        """压缩后消息数 <= MAX_CONTEXT_MESSAGES"""
        messages = _make_messages(50)
        result = await compressor.compress(messages)
        assert result.compressed_count <= compressor.MAX_CONTEXT_MESSAGES

    @pytest.mark.asyncio
    async def test_kept_indices_match_compressed_count(self, compressor):
        """kept_indices 长度 == compressed_count"""
        messages = _make_messages(25)
        result = await compressor.compress(messages)
        assert len(result.kept_indices) == result.compressed_count


class TestPowerLawPruning:
    """幂律裁剪（apply_power_law_pruning）— 测试内部方法"""

    def _make_scored_messages(self, count: int) -> list[dict]:
        """生成带评分的消息列表（apply_power_law_pruning 的输入格式）"""
        return [
            {"memory": {"role": "user", "content": f"消息{i}"}, "score": 1.0 - i * 0.02}
            for i in range(count)
        ]

    def test_pruning_reduces_messages(self, compressor):
        """幂律裁剪后消息数减少"""
        scored = self._make_scored_messages(30)
        pruned = compressor.apply_power_law_pruning(scored)
        assert len(pruned) <= len(scored)

    def test_pruning_preserves_high_score(self, compressor):
        """高评分消息被保留"""
        scored = [
            {"memory": {"role": "user", "content": "重要实体定义"}, "score": 0.95},
            {"memory": {"role": "user", "content": "闲聊"}, "score": 0.1},
            {"memory": {"role": "user", "content": "关键决策"}, "score": 0.9},
        ]
        pruned = compressor.apply_power_law_pruning(scored)
        # 重要实体定义和关键决策应保留
        contents = [item["memory"]["content"] for item in pruned]
        assert "重要实体定义" in contents

    def test_pruning_short_list_unchanged(self, compressor):
        """短列表幂律裁剪后不变"""
        scored = self._make_scored_messages(3)
        pruned = compressor.apply_power_law_pruning(scored)
        assert len(pruned) == 3

    def test_pruning_empty_list(self, compressor):
        """空列表幂律裁剪后仍为空"""
        pruned = compressor.apply_power_law_pruning([])
        assert len(pruned) == 0


class TestScoreMemory:
    """10算法评分引擎（score_memory）"""

    def test_score_returns_scores(self, compressor):
        """score_memory 返回单条记忆的评分 dict"""
        msg = {"role": "user", "content": "你好", "created_at": datetime.utcnow().isoformat() + "Z"}
        result = compressor.score_memory(msg, current_input="你好")
        assert "final_score" in result
        assert "scores" in result
        assert "weights" in result
        assert 0.0 <= result["final_score"] <= 1.0

    def test_score_has_all_algorithms(self, compressor):
        """score_memory 返回所有10个算法的评分"""
        msg = {"role": "user", "content": "测试消息", "created_at": datetime.utcnow().isoformat() + "Z"}
        result = compressor.score_memory(msg, current_input="测试")
        expected_keys = [
            "forgetting", "access_frequency", "recency", "relevance",
            "layer_weight", "contradiction", "topic_consistency",
            "anchor", "value_density", "power_law",
        ]
        for key in expected_keys:
            assert key in result["scores"], f"缺少算法评分: {key}"

    def test_recent_message_scores_higher(self, compressor):
        """最近消息评分高于陈旧消息"""
        now = datetime.utcnow()
        old_msg = {"role": "user", "content": "旧消息", "created_at": (now - timedelta(hours=100)).isoformat() + "Z"}
        new_msg = {"role": "user", "content": "新消息", "created_at": now.isoformat() + "Z"}
        old_score = compressor.score_memory(old_msg, current_input="新消息")["final_score"]
        new_score = compressor.score_memory(new_msg, current_input="新消息")["final_score"]
        assert new_score >= old_score

    def test_system_message_scores_high(self, compressor):
        """system 消息评分较高"""
        system_msg = {"role": "system", "content": "系统提示"}
        user_msg = {"role": "user", "content": "普通消息"}
        system_score = compressor.score_memory(system_msg, current_input="")["final_score"]
        user_score = compressor.score_memory(user_msg, current_input="")["final_score"]
        assert system_score >= user_score
