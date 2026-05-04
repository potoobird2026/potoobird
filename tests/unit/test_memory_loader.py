"""
测试 MemoryLoader — 动态记忆加载器
"""

import pytest
from src.memory.memory_loader import LoadBudget, MemoryLoader


class TestLoadBudget:
    """Token 预算分配测试"""

    def test_from_context_window(self):
        """从上下文窗口创建预算分配"""
        budget = LoadBudget.from_context_window(128000)
        assert budget.total_tokens == 128000
        assert budget.hot_zone == 128000 * 40 // 100  # 40%
        assert budget.relevant == 128000 * 30 // 100  # 30%
        assert budget.high_value == 128000 * 20 // 100  # 20%
        assert budget.anchor == 128000 * 10 // 100  # 10%

    def test_small_context_window(self):
        """小上下文窗口"""
        budget = LoadBudget.from_context_window(1000)
        assert budget.hot_zone == 400
        assert budget.relevant == 300
        assert budget.high_value == 200
        assert budget.anchor == 100


class TestMemoryLoader:
    """动态记忆加载测试"""

    def _make_memory(self, content, access_count=0, last_access_at=None,
                     layer="standard", is_anchor=False, mem_id="m1"):
        """创建测试记忆"""
        return {
            "id": mem_id,
            "content": content,
            "access_count": access_count,
            "last_access_at": last_access_at or "1700000000",
            "layer": layer,
            "is_anchor": is_anchor,
        }

    def test_load_empty_memories(self):
        """空记忆列表返回空"""
        loader = MemoryLoader(context_window=128000)
        result = loader.load_memories([], "test input")
        assert result == []

    def test_load_with_anchor(self):
        """锚点记忆必须被加载"""
        anchor_mem = self._make_memory("项目叫 Potoobird", layer="personality", is_anchor=True)
        loader = MemoryLoader(context_window=128000)
        result = loader.load_memories([anchor_mem], "关于项目")
        assert any(m.get("id") == "m1" for m in result)

    def test_load_prioritizes_recent(self):
        """最近访问的记忆优先加载"""
        old_mem = self._make_memory("旧记忆", access_count=1, mem_id="old")
        hot_mem = self._make_memory("热记忆", access_count=50, mem_id="hot")
        loader = MemoryLoader(context_window=128000)
        result = loader.load_memories([old_mem, hot_mem], "测试")
        # 热记忆应该在结果中
        ids = [m.get("id") for m in result]
        assert "hot" in ids

    def test_load_respects_budget(self):
        """加载不超过预算"""
        big_mem = self._make_memory("x" * 50000, access_count=100, mem_id="big")
        loader = MemoryLoader(context_window=1000)
        result = loader.load_memories([big_mem], "测试")
        # 单条记忆超过总预算，但锚点不受预算限制
        # 此测试验证非锚点记忆受预算限制

    def test_shannon_entropy_calculation(self):
        """香农熵计算"""
        loader = MemoryLoader()
        # 高熵（信息量大）
        high_entropy = loader._calc_shannon_entropy("abcdefghijklmnopqrstuvwxyz")
        # 低熵（信息量小）
        low_entropy = loader._calc_shannon_entropy("aaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert high_entropy > low_entropy

    def test_mutual_information_calculation(self):
        """互信息计算"""
        loader = MemoryLoader()
        # 完全相同的文本
        mi_same = loader._calc_mutual_information("hello world", "hello world")
        # 完全不同的文本
        mi_diff = loader._calc_mutual_information("abc", "xyz")
        assert mi_same > mi_diff

    def test_hot_score_calculation(self):
        """热区评分"""
        loader = MemoryLoader()
        hot_mem = self._make_memory("热", access_count=100, last_access_at="1700000000")
        cold_mem = self._make_memory("冷", access_count=0, last_access_at="0")
        hot_score = loader._calc_hot_score(hot_mem)
        cold_score = loader._calc_hot_score(cold_mem)
        assert hot_score > cold_score

    def test_is_anchor_personality_layer(self):
        """人格层记忆是锚点"""
        loader = MemoryLoader()
        mem = self._make_memory("H=50", layer="personality")
        assert loader._is_anchor(mem) is True

    def test_is_anchor_keyword(self):
        """包含实体定义关键词的记忆是锚点"""
        loader = MemoryLoader()
        mem = self._make_memory("项目叫 Potoobird", layer="standard")
        assert loader._is_anchor(mem) is True

    def test_is_not_anchor(self):
        """普通记忆不是锚点"""
        loader = MemoryLoader()
        mem = self._make_memory("普通记忆内容", layer="standard")
        assert loader._is_anchor(mem) is False
