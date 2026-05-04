"""性能基线测试"""

import os
import time

import pytest

from src.context.algorithms.confidence_threshold import ConfidenceThreshold
from src.context.algorithms.logistic_growth import MemoryCapacityManager
from src.memory.storage.sqlite_storage import SQLiteStorage
from src.observability.metrics import MetricsCollector

# CI 环境资源受限，放宽阈值
_CI = os.environ.get("CI", "false").lower() == "true"
_FACTOR = 3.0 if _CI else 1.0


class TestPerformanceBaseline:
    """性能基线测试 — 关键操作必须在规定时间内完成"""

    @pytest.fixture
    def tmp_db(self, tmp_path):
        return str(tmp_path / "perf_test.db")

    @pytest.fixture
    def storage(self, tmp_db):
        return SQLiteStorage(tmp_db)

    # ---- 记忆操作性能 ----

    @pytest.mark.asyncio
    async def test_memory_write_under_100ms(self, storage):
        """记忆写入必须 < 100ms（CI 放宽到 300ms）"""
        from src.memory.storage.base import Memory
        m = Memory(content="性能测试记忆", layer="core")

        start = time.perf_counter()
        await storage.upsert(m)
        elapsed_ms = (time.perf_counter() - start) * 1000

        limit = 100 * _FACTOR
        assert elapsed_ms < limit, f"记忆写入 {elapsed_ms:.2f}ms 超过 {limit:.0f}ms 基线"

    @pytest.mark.asyncio
    async def test_memory_search_under_100ms(self, storage):
        """记忆检索必须 < 100ms（CI 放宽到 300ms）"""
        from src.memory.storage.base import Memory
        for i in range(100):
            m = Memory(content=f"记忆内容 {i}", layer="core")
            await storage.upsert(m)

        start = time.perf_counter()
        await storage.search("记忆", limit=10)
        elapsed_ms = (time.perf_counter() - start) * 1000

        limit = 100 * _FACTOR
        assert elapsed_ms < limit, f"记忆检索 {elapsed_ms:.2f}ms 超过 {limit:.0f}ms 基线"

    @pytest.mark.asyncio
    async def test_memory_count_under_50ms(self, storage):
        """记忆计数必须 < 50ms（CI 放宽到 150ms）"""
        start = time.perf_counter()
        await storage.count()
        elapsed_ms = (time.perf_counter() - start) * 1000

        limit = 50 * _FACTOR
        assert elapsed_ms < limit, f"记忆计数 {elapsed_ms:.2f}ms 超过 {limit:.0f}ms 基线"

    # ---- 算法性能 ----

    def test_logistic_growth_calculation(self):
        """Logistic Growth 计算性能"""
        mgr = MemoryCapacityManager()

        start = time.perf_counter()
        for _ in range(1000):
            mgr.get_write_probability(5000)
            mgr.get_phase(5000)
        elapsed_ms = (time.perf_counter() - start) * 1000

        limit = 200 * _FACTOR
        assert elapsed_ms < limit, f"1000次 Logistic Growth 计算 {elapsed_ms:.2f}ms 超过基线"

    def test_confidence_threshold_calculation(self):
        """置信度阈值计算性能"""
        ct = ConfidenceThreshold()

        start = time.perf_counter()
        for i in range(100):
            ct.should_clarify(0.5 + i * 0.005, "task")
            ct.evaluate(0.5 + i * 0.005)
        elapsed_ms = (time.perf_counter() - start) * 1000

        limit = 200 * _FACTOR
        assert elapsed_ms < limit, f"100次置信度计算 {elapsed_ms:.2f}ms 超过基线"

    # ---- 可观测性性能 ----

    def test_metrics_collection(self):
        """指标收集性能"""
        metrics = MetricsCollector()

        start = time.perf_counter()
        for i in range(1000):
            metrics.increment("requests", 1)
            metrics.set_gauge("sessions", float(i))
        elapsed_ms = (time.perf_counter() - start) * 1000

        limit = 100 * _FACTOR
        assert elapsed_ms < limit, f"1000次指标操作 {elapsed_ms:.2f}ms 超过基线"
