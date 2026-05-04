"""
单元测试 — 健康检查
"""

from unittest.mock import AsyncMock, MagicMock

from src.observability.health import HealthChecker, HealthStatus


class TestHealthStatus:
    def test_default_ok(self):
        s = HealthStatus()
        assert s.ok is True
        assert s.uptime_seconds == 0.0
        assert s.memory_count == 0

    def test_to_dict(self):
        s = HealthStatus(ok=True, memory_count=5, components={"storage": "ok"})
        d = s.to_dict()
        assert d["ok"] is True
        assert d["memory_count"] == 5
        assert d["components"]["storage"] == "ok"

    def test_to_dict_with_error(self):
        s = HealthStatus(ok=False, last_error="storage down")
        d = s.to_dict()
        assert d["ok"] is False
        assert d["last_error"] == "storage down"


class TestHealthChecker:
    def test_check_no_storage(self):
        """无 storage 时也能检查"""
        hc = HealthChecker()
        status = hc.check()
        assert status.ok is True
        assert status.uptime_seconds >= 0

    def test_check_with_mock_storage(self):
        mock_storage = MagicMock()
        mock_storage.count = AsyncMock(return_value=42)

        hc = HealthChecker(storage=mock_storage)
        status = hc.check()
        assert status.ok is True
        assert status.memory_count == 42
        assert status.components["storage"] == "ok"

    def test_check_storage_error(self):
        mock_storage = MagicMock()
        mock_storage.count = AsyncMock(side_effect=Exception("DB locked"))

        hc = HealthChecker(storage=mock_storage)
        status = hc.check()
        assert status.ok is False
        assert "DB locked" in status.last_error
        assert "error" in status.components["storage"]

    def test_check_with_metrics(self):
        mock_metrics = MagicMock()
        mock_metrics.summary.return_value = {"_counters": {"llm_calls": 10}}

        hc = HealthChecker(metrics=mock_metrics)
        status = hc.check()
        assert status.components["metrics"] == "ok"
        assert status.components["counters"] == {"llm_calls": 10}

    def test_check_metrics_error(self):
        mock_metrics = MagicMock()
        mock_metrics.summary.side_effect = Exception("metrics down")

        hc = HealthChecker(metrics=mock_metrics)
        status = hc.check()
        assert "error" in status.components["metrics"]

    def test_uptime_increases(self):
        import time
        hc = HealthChecker()
        time.sleep(0.1)
        status = hc.check()
        assert status.uptime_seconds >= 0
