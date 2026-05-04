"""
指标采集 — V1 内存版 + V2 Prometheus 格式导出

V1 兼容接口：MetricsCollector（内存计数器）
V2 新增接口：PrometheusExporter（Prometheus text format 导出）

设计决策（ADR-010）：
- 不引入 prometheus_client 依赖（减少外部耦合）
- 自建轻量 Prometheus text format 生成器
- V1 MetricsCollector 作为数据源，PrometheusExporter 作为输出适配器
- 符合 G-001 配置外部化：指标端口、路径通过 Settings 配置
"""

import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("long_agent.observability")


# ─────────────────────────────────────────────
# V1 兼容层（保留，现有测试依赖）
# ─────────────────────────────────────────────

@dataclass
class MetricSnapshot:
    """指标快照 — V1 兼容"""

    counters: dict[str, int]
    timings: dict[str, list[float]]
    errors: dict[str, int]


class MetricsCollector:
    """指标采集器 — V1 内存版（兼容保留）

    V2 中作为 PrometheusExporter 的数据源。
    所有 increment/record_timing/record_error 调用会同步更新内部状态，
    供 PrometheusExporter 读取并输出。
    """

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._timings: dict[str, list[float]] = defaultdict(list)
        self._errors: dict[str, int] = defaultdict(int)
        # V2：Prometheus 风格的 buckets
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}

    def increment(self, name: str, value: int = 1):
        self._counters[name] += value

    def record_timing(self, name: str, duration_ms: float):
        self._timings[name].append(duration_ms)
        # 同步到 histogram（V2）
        self._histograms[name].append(duration_ms)
        # 只保留最近 1000 条（V1 兼容）
        if len(self._timings[name]) > 1000:
            self._timings[name] = self._timings[name][-1000:]
        if len(self._histograms[name]) > 1000:
            self._histograms[name] = self._histograms[name][-1000:]

    def record_error(self, name: str):
        self._errors[name] += 1

    def set_gauge(self, name: str, value: float):
        """V2 新增：设置 Gauge 值"""
        self._gauges[name] = value

    def get_gauge(self, name: str) -> float:
        return self._gauges.get(name, 0.0)

    @contextmanager
    def timer(self, name: str):
        """计时上下文管理器"""
        start = time.monotonic()
        try:
            yield
        except Exception:
            self.record_error(f"{name}_error")
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            self.record_timing(name, elapsed_ms)

    def snapshot(self) -> MetricSnapshot:
        """获取指标快照 — V1 兼容"""
        return MetricSnapshot(
            counters=dict(self._counters),
            timings={k: list(v) for k, v in self._timings.items()},
            errors=dict(self._errors),
        )

    def summary(self) -> dict:
        """汇总统计 — V1 兼容"""
        result = {}
        for name, times in self._timings.items():
            if times:
                result[name] = {
                    "count": len(times),
                    "avg_ms": sum(times) / len(times),
                    "min_ms": min(times),
                    "max_ms": max(times),
                }
        result["_counters"] = dict(self._counters)
        result["_errors"] = dict(self._errors)
        result["_gauges"] = dict(self._gauges)
        return result

    def reset(self):
        self._counters.clear()
        self._timings.clear()
        self._errors.clear()
        self._histograms.clear()
        self._gauges.clear()

    # ─────────────────────────────────────────
    # V2 Prometheus 导出接口
    # ─────────────────────────────────────────

    def prometheus_metrics(self) -> str:
        """生成 Prometheus text format 输出

        输出格式遵循 Prometheus exposition format：
        # HELP name description
        # TYPE name type
        name{labels} value
        """
        lines: list[str] = []

        # Counters
        for name, value in sorted(self._counters.items()):
            safe_name = self._safe_name(name)
            lines.append(f"# HELP {safe_name} Counter metric from Long Agent")
            lines.append(f"# TYPE {safe_name} counter")
            lines.append(f"{safe_name} {value}")

        # Errors（也是 counter）
        for name, value in sorted(self._errors.items()):
            safe_name = self._safe_name(name)
            lines.append(f"# HELP {safe_name} Error counter from Long Agent")
            lines.append(f"# TYPE {safe_name} counter")
            lines.append(f"{safe_name} {value}")

        # Gauges
        for name, value in sorted(self._gauges.items()):
            safe_name = self._safe_name(name)
            lines.append(f"# HELP {safe_name} Gauge metric from Long Agent")
            lines.append(f"# TYPE {safe_name} gauge")
            lines.append(f"{safe_name} {value}")

        # Timings → Histogram
        default_buckets = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
        for name, values in sorted(self._histograms.items()):
            safe_name = self._safe_name(name)
            lines.append(f"# HELP {safe_name}_duration_ms Request duration in milliseconds")
            lines.append(f"# TYPE {safe_name}_duration_ms histogram")

            bucket_counts: dict[float, int] = {}
            for b in default_buckets:
                bucket_counts[b] = 0
            total = 0
            for v in values:
                total += 1
                for b in default_buckets:
                    if v <= b:
                        bucket_counts[b] += 1

            for b in default_buckets:
                lines.append(f'{safe_name}_duration_ms_bucket{{le="{b}"}} {bucket_counts[b]}')
            lines.append(f'{safe_name}_duration_ms_bucket{{le="+Inf"}} {total}')
            lines.append(f"{safe_name}_duration_ms_sum {sum(values)}")
            lines.append(f"{safe_name}_duration_ms_count {total}")

        lines.append("")  # trailing newline
        return "\n".join(lines)

    @staticmethod
    def _safe_name(name: str) -> str:
        """将指标名转换为 Prometheus 安全格式"""
        return name.replace(".", "_").replace("-", "_").replace(" ", "_")
