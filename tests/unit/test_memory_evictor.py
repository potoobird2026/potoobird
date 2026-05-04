"""
测试 MemoryEvictor — 记忆淘汰引擎
"""

import pytest
from src.context.algorithms.logistic_growth import MemoryCapacityManager
from src.memory.memory_evictor import EvictionResult, MemoryEvictor


class TestMemoryCapacityManager:
    """容量管理器测试（宽进严出）"""

    def test_write_probability_always_one(self):
        """写入概率始终为 1.0（宽进）"""
        mgr = MemoryCapacityManager(k=10000, alpha=1.5)
        assert mgr.get_write_probability(0) == 1.0
        assert mgr.get_write_probability(5000) == 1.0
        assert mgr.get_write_probability(9999) == 1.0
        assert mgr.get_write_probability(10000) == 1.0

    def test_eviction_score_increases_with_density(self):
        """淘汰评分随密度增加"""
        mgr = MemoryCapacityManager(k=10000, alpha=1.5)
        score_low = mgr.get_eviction_score(1000)   # 10% 密度
        score_mid = mgr.get_eviction_score(5000)   # 50% 密度
        score_high = mgr.get_eviction_score(9000)  # 90% 密度
        assert score_low < score_mid < score_high

    def test_eviction_score_formula(self):
        """淘汰公式：(N/K)^α"""
        mgr = MemoryCapacityManager(k=10000, alpha=2.0)
        # N=5000, K=10000, α=2 → (0.5)^2 = 0.25
        assert abs(mgr.get_eviction_score(5000) - 0.25) < 0.01

    def test_should_evict_below_threshold(self):
        """低于阈值不淘汰"""
        mgr = MemoryCapacityManager(k=10000, alpha=1.5)
        # N=5000 → (0.5)^1.5 ≈ 0.354 < 0.85
        assert mgr.should_evict(5000) is False

    def test_should_evict_above_threshold(self):
        """高于阈值淘汰"""
        mgr = MemoryCapacityManager(k=10000, alpha=1.5)
        # N=9500 → (0.95)^1.5 ≈ 0.927 > 0.85
        assert mgr.should_evict(9500) is True

    def test_phase_normal(self):
        """正常阶段"""
        mgr = MemoryCapacityManager(k=10000, alpha=1.5)
        mgr.update_count(5000)
        assert mgr.get_phase() == "normal"

    def test_phase_eviction(self):
        """淘汰阶段"""
        mgr = MemoryCapacityManager(k=10000, alpha=1.5)
        mgr.update_count(9500)
        assert mgr.get_phase() == "eviction"


class TestMemoryEvictor:
    """记忆淘汰引擎测试"""

    def _make_memory(self, content, access_count=0, layer="standard",
                     is_anchor=False, mem_id="m1"):
        """创建测试记忆"""
        return {
            "id": mem_id,
            "content": content,
            "access_count": access_count,
            "layer": layer,
            "is_anchor": is_anchor,
        }

    def test_no_eviction_when_far_from_capacity(self):
        """远低于容量时不淘汰"""
        evictor = MemoryEvictor(alpha=1.5, threshold=0.85)
        memories = [self._make_memory(f"记忆{i}", mem_id=f"m{i}") for i in range(100)]
        result = evictor.evict(memories, current_count=100, capacity_k=10000)
        assert result.evicted_count == 0

    def test_eviction_triggered_near_capacity(self):
        """接近容量时触发淘汰"""
        evictor = MemoryEvictor(alpha=1.5, threshold=0.85)
        memories = [self._make_memory(f"记忆{i}", access_count=i, mem_id=f"m{i}") for i in range(100)]
        # N=9500, K=10000 → eviction_score ≈ 0.927 > 0.85
        result = evictor.evict(memories, current_count=9500, capacity_k=10000)
        assert result.evicted_count > 0

    def test_anchor_protected(self):
        """锚点记忆不被淘汰"""
        evictor = MemoryEvictor(alpha=1.5, threshold=0.85)
        anchor = self._make_memory("项目叫 Potoobird", layer="personality", is_anchor=True, mem_id="anchor")
        normal = self._make_memory("普通记忆", access_count=0, mem_id="normal")
        memories = [anchor, normal]
        # 触发淘汰
        result = evictor.evict(memories, current_count=9500, capacity_k=10000)
        evicted_ids = result.evicted_ids
        assert "anchor" not in evicted_ids

    def test_low_score_evicted_first(self):
        """低分记忆先淘汰"""
        evictor = MemoryEvictor(alpha=1.5, threshold=0.85)
        high_score = self._make_memory("高分", access_count=100, mem_id="high")
        low_score = self._make_memory("低分", access_count=0, mem_id="low")
        memories = [high_score, low_score]
        result = evictor.evict(memories, current_count=9500, capacity_k=10000)
        assert "low" in result.evicted_ids

    def test_eviction_result_fields(self):
        """淘汰结果字段完整"""
        evictor = MemoryEvictor(alpha=1.5, threshold=0.85)
        memories = [self._make_memory(f"记忆{i}", mem_id=f"m{i}") for i in range(50)]
        result = evictor.evict(memories, current_count=9500, capacity_k=10000)
        assert isinstance(result, EvictionResult)
        assert result.evicted_count >= 0
        assert isinstance(result.evicted_ids, list)
        assert result.remaining_count >= 0
        assert result.eviction_score > 0

    def test_simple_score_calculation(self):
        """简化版评分（无 compressor）"""
        evictor = MemoryEvictor(compressor=None)
        mem = self._make_memory("测试", access_count=10)
        score = evictor._simple_score(mem, "测试输入")
        assert 0.0 <= score <= 1.0

    def test_is_anchor_personality(self):
        """人格层是锚点"""
        evictor = MemoryEvictor()
        mem = {"layer": "personality", "content": "H=50"}
        assert evictor._is_anchor(mem) is True

    def test_is_anchor_marked(self):
        """显式标记为锚点"""
        evictor = MemoryEvictor()
        mem = {"layer": "standard", "is_anchor": True, "content": "重要"}
        assert evictor._is_anchor(mem) is True

    def test_is_not_anchor_normal(self):
        """普通记忆不是锚点"""
        evictor = MemoryEvictor()
        mem = {"layer": "standard", "content": "普通内容"}
        assert evictor._is_anchor(mem) is False
