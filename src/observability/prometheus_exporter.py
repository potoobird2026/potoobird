"""
PrometheusExporter — 可观测性指标导出器

设计文档：DESIGN-V2.md §12.1

指标：
- LLM_LATENCY: LLM 调用延迟（Histogram）
- MEMORY_RETRIEVAL_LATENCY: 记忆检索延迟（Histogram）
- AGENT_LOOP_DURATION: 主循环耗时（Histogram）
- COMPRESSION_RATIO: 上下文压缩比（Histogram）
- LLM_ERROR_RATE: LLM 错误计数（Counter）

状态持久化：
- save_state(): 将指标快照保存到 JSON 文件
- load_state(): 从 JSON 文件加载指标快照
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("long_agent.observability")


# ============================================================
# 指标收集（无 prometheus_client 依赖时的兼容实现）
# ============================================================


class _HistogramCompat:
    """Histogram 兼容实现（有 prometheus_client 时替换为真实 Histogram）"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._values: list[float] = []

    def observe(self, value: float):
        self._values.append(value)

    def collect_snapshot(self) -> dict:
        if not self._values:
            return {"name": self.name, "count": 0, "sum": 0.0, "avg": 0.0}
        return {
            "name": self.name,
            "count": len(self._values),
            "sum": sum(self._values),
            "avg": sum(self._values) / len(self._values),
            "min": min(self._values),
            "max": max(self._values),
            "p95": (
                sorted(self._values)[int(len(self._values) * 0.95)]
                if len(self._values) > 1
                else self._values[0]
            ),
        }


class _CounterCompat:
    """Counter 兼容实现（有 prometheus_client 时替换为真实 Counter）"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._count: int = 0

    def inc(self, amount: int = 1):
        self._count += amount

    def collect_snapshot(self) -> dict:
        return {"name": self.name, "count": self._count}


# ============================================================
# PrometheusExporter
# ============================================================


@dataclass
class MetricSnapshot:
    """指标快照"""

    timestamp: str = ""
    llm_latency: dict = field(default_factory=dict)
    memory_retrieval_latency: dict = field(default_factory=dict)
    agent_loop_duration: dict = field(default_factory=dict)
    compression_ratio: dict = field(default_factory=dict)
    llm_errors: dict = field(default_factory=dict)


class PrometheusExporter:
    """
    V2 升级：集成 Prometheus + Grafana

    V1：结构化 JSON 日志 + perf_counter → 日志
    V2：Prometheus histogram + counter + 告警规则

    使用方式：
        exporter = PrometheusExporter()
        with exporter.track_llm_latency():
            result = llm.call(...)
        exporter.save_state("/tmp/metrics.json")
    """

    def __init__(self, pushgateway_url: str = None, state_path: str = None):
        """
        Args:
            pushgateway_url: Prometheus Pushgateway URL（None 时不推送）
            state_path: 状态持久化文件路径
        """
        self._pushgateway_url = pushgateway_url
        self._state_path = state_path or "./data/metrics_snapshot.json"

        # 关键指标
        self.LLM_LATENCY = _HistogramCompat("llm_call_latency_seconds", "LLM 调用延迟")
        self.MEMORY_RETRIEVAL_LATENCY = _HistogramCompat(
            "memory_retrieval_latency_seconds", "记忆检索延迟"
        )
        self.AGENT_LOOP_DURATION = _HistogramCompat("agent_loop_duration_seconds", "主循环耗时")
        self.COMPRESSION_RATIO = _HistogramCompat("context_compression_ratio", "上下文压缩比")
        self.LLM_ERROR_RATE = _CounterCompat("llm_errors_total", "LLM 错误计数")

        logger.info("PrometheusExporter 初始化完成")

    # --- 追踪上下文管理器 ---

    def track_llm_latency(self):
        """追踪 LLM 调用延迟"""
        return _LatencyTracker(self.LLM_LATENCY)

    def track_memory_retrieval_latency(self):
        """追踪记忆检索延迟"""
        return _LatencyTracker(self.MEMORY_RETRIEVAL_LATENCY)

    def track_agent_loop(self):
        """追踪主循环耗时"""
        return _LatencyTracker(self.AGENT_LOOP_DURATION)

    # --- 直接记录接口 ---

    def record_compression_ratio(self, ratio: float):
        """
        记录上下文压缩比

        Args:
            ratio: 压缩比 ∈ [0, 1]，1.0 = 无压缩
        """
        self.COMPRESSION_RATIO.observe(ratio)

    def record_llm_error(self, error_type: str = "unknown"):
        """
        记录 LLM 错误

        Args:
            error_type: 错误类型
        """
        self.LLM_ERROR_RATE.inc()
        logger.warning(f"LLM 错误记录: {error_type}")

    # --- 状态持久化 ---

    def save_state(self, path: str = None) -> str:
        """
        将指标快照保存到 JSON 文件

        Args:
            path: 保存路径（None 时使用默认路径）

        Returns:
            str: 保存的文件路径
        """
        save_path = path or self._state_path
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

        snapshot = MetricSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            llm_latency=self.LLM_LATENCY.collect_snapshot(),
            memory_retrieval_latency=self.MEMORY_RETRIEVAL_LATENCY.collect_snapshot(),
            agent_loop_duration=self.AGENT_LOOP_DURATION.collect_snapshot(),
            compression_ratio=self.COMPRESSION_RATIO.collect_snapshot(),
            llm_errors=self.LLM_ERROR_RATE.collect_snapshot(),
        )

        data = {
            "timestamp": snapshot.timestamp,
            "metrics": {
                "llm_latency": snapshot.llm_latency,
                "memory_retrieval_latency": snapshot.memory_retrieval_latency,
                "agent_loop_duration": snapshot.agent_loop_duration,
                "compression_ratio": snapshot.compression_ratio,
                "llm_errors": snapshot.llm_errors,
            },
        }

        with open(save_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"指标快照已保存: {save_path}")
        return save_path

    def load_state(self, path: str = None) -> Optional[dict]:
        """
        从 JSON 文件加载指标快照

        Args:
            path: 文件路径（None 时使用默认路径）

        Returns:
            dict or None: 快照数据
        """
        load_path = path or self._state_path
        if not os.path.exists(load_path):
            logger.warning(f"快照文件不存在: {load_path}")
            return None

        with open(load_path, "r") as f:
            data = json.load(f)

        logger.info(f"指标快照已加载: {load_path}")
        return data

    def get_snapshot(self) -> MetricSnapshot:
        """获取当前指标快照（不持久化）"""
        return MetricSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            llm_latency=self.LLM_LATENCY.collect_snapshot(),
            memory_retrieval_latency=self.MEMORY_RETRIEVAL_LATENCY.collect_snapshot(),
            agent_loop_duration=self.AGENT_LOOP_DURATION.collect_snapshot(),
            compression_ratio=self.COMPRESSION_RATIO.collect_snapshot(),
            llm_errors=self.LLM_ERROR_RATE.collect_snapshot(),
        )


class _LatencyTracker:
    """延迟追踪上下文管理器"""

    def __init__(self, histogram: _HistogramCompat):
        self._histogram = histogram
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.perf_counter() - self._start
        self._histogram.observe(elapsed)
        return False  # 不吞异常
