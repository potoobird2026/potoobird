"""
单元测试 — V2 可观测性升级

覆盖：
- MetricsCollector 新增接口（Gauge、Prometheus 导出）
- HealthChecker 新增接口（register_component、check_async）
- HTTP 端点（create_observability_router）
- JSON 日志格式
"""

import json
import logging
from unittest.mock import AsyncMock

import pytest

from src.observability.health import HealthChecker, HealthStatus, health_response
from src.observability.metrics import MetricsCollector

# ─────────────────────────────────────────────
# MetricsCollector V2 新增测试
# ─────────────────────────────────────────────

class TestMetricsCollectorV2:
    """V2 新增接口测试"""

    def test_set_and_get_gauge(self):
        m = MetricsCollector()
        m.set_gauge("active_sessions", 5.0)
        assert m.get_gauge("active_sessions") == 5.0

    def test_gauge_default_zero(self):
        m = MetricsCollector()
        assert m.get_gauge("nonexistent") == 0.0

    def test_gauge_overwrite(self):
        m = MetricsCollector()
        m.set_gauge("x", 1.0)
        m.set_gauge("x", 2.0)
        assert m.get_gauge("x") == 2.0

    def test_summary_includes_gauges(self):
        m = MetricsCollector()
        m.set_gauge("sessions", 3.0)
        s = m.summary()
        assert s["_gauges"]["sessions"] == 3.0

    def test_prometheus_metrics_not_empty(self):
        m = MetricsCollector()
        m.increment("requests", 5)
        prom = m.prometheus_metrics()
        assert "requests_total 5" in prom or "requests 5" in prom

    def test_prometheus_includes_help_and_type(self):
        m = MetricsCollector()
        m.increment("llm_calls", 1)
        prom = m.prometheus_metrics()
        assert "# HELP" in prom
        assert "# TYPE" in prom

    def test_prometheus_histogram_output(self):
        m = MetricsCollector()
        m.record_timing("chat", 10.0)
        m.record_timing("chat", 20.0)
        m.record_timing("chat", 500.0)
        prom = m.prometheus_metrics()
        assert "chat_duration_ms_bucket" in prom
        assert "chat_duration_ms_sum" in prom
        assert "chat_duration_ms_count 3" in prom

    def test_prometheus_gauge_output(self):
        m = MetricsCollector()
        m.set_gauge("active_sessions", 7.0)
        prom = m.prometheus_metrics()
        assert "active_sessions" in prom
        assert "gauge" in prom

    def test_prometheus_safe_name(self):
        m = MetricsCollector()
        assert m._safe_name("llm.call.duration") == "llm_call_duration"
        assert m._safe_name("error-rate") == "error_rate"
        assert m._safe_name("my metric") == "my_metric"

    def test_prometheus_empty_collector(self):
        m = MetricsCollector()
        prom = m.prometheus_metrics()
        assert prom.strip() == ""

    def test_reset_clears_histograms_and_gauges(self):
        m = MetricsCollector()
        m.record_timing("x", 1.0)
        m.set_gauge("y", 2.0)
        m.reset()
        assert len(m._histograms) == 0
        assert len(m._gauges) == 0


# ─────────────────────────────────────────────
# HealthChecker V2 新增测试
# ─────────────────────────────────────────────

class TestHealthCheckerV2:
    """V2 新增接口测试"""

    def test_register_component(self):
        hc = HealthChecker()
        mock_check = AsyncMock(return_value=True)
        hc.register_component("llm", mock_check, critical=True)
        assert "llm" in hc._components

    @pytest.mark.asyncio
    async def test_check_async_all_healthy(self):
        hc = HealthChecker()
        hc.register_component("test", AsyncMock(return_value=True))
        status = await hc.check_async()
        assert status.ok is True
        assert status.components["test"] == "ok"

    @pytest.mark.asyncio
    async def test_check_async_critical_failure(self):
        hc = HealthChecker()
        hc.register_component("db", AsyncMock(return_value=False), critical=True)
        status = await hc.check_async()
        assert status.ok is False
        assert status.components["db"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_async_non_critical_failure(self):
        hc = HealthChecker()
        hc.register_component("cache", AsyncMock(return_value=False), critical=False)
        status = await hc.check_async()
        assert status.ok is True  # 非关键组件失败不影响整体
        assert status.components["cache"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_async_component_exception(self):
        hc = HealthChecker()
        hc.register_component("x", AsyncMock(side_effect=Exception("boom")), critical=True)
        status = await hc.check_async()
        assert status.ok is False
        assert "error" in status.components["x"]

    @pytest.mark.asyncio
    async def test_check_async_no_components(self):
        hc = HealthChecker()
        status = await hc.check_async()
        assert status.ok is True


class TestHealthResponse:
    """health_response 格式化测试"""

    def test_healthy_response(self):
        status = HealthStatus(ok=True, uptime_seconds=10.5)
        resp = health_response(status)
        assert resp["status"] == "healthy"
        assert resp["uptime_seconds"] == 10.5

    def test_unhealthy_response(self):
        status = HealthStatus(ok=False, uptime_seconds=0, last_error="db down")
        resp = health_response(status, include_details=False)
        assert resp["status"] == "unhealthy"
        assert "components" not in resp

    def test_response_with_details(self):
        status = HealthStatus(ok=True, components={"db": "ok", "llm": "ok"})
        resp = health_response(status, include_details=True)
        assert resp["components"] == {"db": "ok", "llm": "ok"}


# ─────────────────────────────────────────────
# HTTP 端点测试（需要 FastAPI）
# ─────────────────────────────────────────────

class TestObservabilityRouter:
    """V2 HTTP 端点测试"""

    @pytest.fixture
    def app(self):
        """创建测试用 FastAPI 应用"""
        try:
            from starlette.testclient import TestClient  # noqa: F401
        except ImportError:
            pytest.skip("starlette 未安装")

        from src.observability.health import HealthChecker
        from src.observability.http_server import create_observability_app
        from src.observability.metrics import MetricsCollector

        metrics = MetricsCollector()
        metrics.increment("requests", 3)
        metrics.set_gauge("sessions", 2.0)
        hc = HealthChecker()

        app = create_observability_app(health_checker=hc, metrics_collector=metrics)
        return app

    @pytest.fixture
    def client(self, app):
        if app is None:
            pytest.skip("FastAPI 未安装")
        from starlette.testclient import TestClient
        return TestClient(app)

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_ready_endpoint(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"

    def test_metrics_endpoint(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        body = resp.text
        assert "requests" in body

    def test_metrics_with_histogram(self, client):
        resp = client.get("/metrics")
        body = resp.text
        # 有 counter 就有 HELP/TYPE
        assert "# HELP" in body
        assert "# TYPE" in body


# ─────────────────────────────────────────────
# JSON 日志格式测试
# ─────────────────────────────────────────────

class TestJsonFormatter:
    """V2 JSON 日志格式测试"""

    def test_json_format_output(self):
        from src.config.settings import _JsonFormatter

        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed

    def test_json_format_with_exception(self):
        from src.config.settings import _JsonFormatter

        formatter = _JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "ERROR"
        assert "exception" in parsed
        assert "test error" in parsed["exception"]

    def test_init_logging_json_mode(self):

        from src.config.settings import init_logging

        # 捕获日志输出
        logger = init_logging(log_level="DEBUG", log_file="/tmp/test_observability.log", json_format=True)  # noqa: E501
        assert logger is not None
        # 清理 handlers 避免影响其他测试
        logger.handlers.clear()
