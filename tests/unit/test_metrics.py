"""
单元测试 — 指标采集
"""

from src.observability.metrics import MetricsCollector


class TestMetricsCollector:
    def test_increment(self):
        m = MetricsCollector()
        m.increment("llm_calls")
        m.increment("llm_calls")
        m.increment("errors", 3)
        assert m._counters["llm_calls"] == 2
        assert m._counters["errors"] == 3

    def test_record_timing(self):
        m = MetricsCollector()
        m.record_timing("chat", 10.0)
        m.record_timing("chat", 20.0)
        assert len(m._timings["chat"]) == 2
        assert m._timings["chat"][0] == 10.0

    def test_timing_trims_to_1000(self):
        m = MetricsCollector()
        for i in range(1005):
            m.record_timing("x", float(i))
        assert len(m._timings["x"]) == 1000
        assert m._timings["x"][-1] == 1004.0

    def test_record_error(self):
        m = MetricsCollector()
        m.record_error("timeout")
        m.record_error("timeout")
        assert m._errors["timeout"] == 2

    def test_timer(self):
        m = MetricsCollector()
        with m.timer("op"):
            pass
        assert len(m._timings["op"]) == 1
        assert m._timings["op"][0] >= 0

    def test_timer_records_error_on_exception(self):
        m = MetricsCollector()
        try:
            with m.timer("op"):
                raise ValueError("fail")
        except ValueError:
            pass
        assert m._errors["op_error"] == 1
        assert len(m._timings["op"]) == 1

    def test_snapshot(self):
        m = MetricsCollector()
        m.increment("calls", 5)
        m.record_timing("chat", 10.0)
        m.record_error("timeout")
        snap = m.snapshot()
        assert snap.counters["calls"] == 5
        assert snap.timings["chat"] == [10.0]
        assert snap.errors["timeout"] == 1

    def test_summary(self):
        m = MetricsCollector()
        m.increment("calls", 3)
        m.record_timing("chat", 10.0)
        m.record_timing("chat", 20.0)
        m.record_error("timeout")
        s = m.summary()
        assert s["chat"]["count"] == 2
        assert s["chat"]["avg_ms"] == 15.0
        assert s["chat"]["min_ms"] == 10.0
        assert s["chat"]["max_ms"] == 20.0
        assert s["_counters"]["calls"] == 3
        assert s["_errors"]["timeout"] == 1

    def test_reset(self):
        m = MetricsCollector()
        m.increment("calls")
        m.record_timing("chat", 10.0)
        m.record_error("timeout")
        m.reset()
        assert len(m._counters) == 0
        assert len(m._timings) == 0
        assert len(m._errors) == 0
