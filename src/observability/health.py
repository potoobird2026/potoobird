"""
健康检查 — V1 内存版 + V2 HTTP 端点

V1：HealthChecker（内存指标快照）
V2：新增 FastAPI Router，暴露 /health 和 /ready 端点

设计决策（ADR-010）：
- /health：存活检查（进程是否正常）
- /ready：就绪检查（存储、LLM、指标是否正常）
- /metrics：Prometheus 格式指标（由 metrics.py 生成）
- 符合 G-001：端口、路径通过配置外部化
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("long_agent.health")


# ─────────────────────────────────────────────
# V1 兼容层
# ─────────────────────────────────────────────

@dataclass
class HealthStatus:
    """健康状态 — V1 兼容"""

    ok: bool = True
    uptime_seconds: float = 0.0
    memory_count: int = 0
    last_backup: str = ""
    last_error: str = ""
    components: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "memory_count": self.memory_count,
            "last_backup": self.last_backup,
            "last_error": self.last_error,
            "components": self.components,
        }


class HealthChecker:
    """健康检查器 — V1 兼容，V2 扩展"""

    def __init__(self, storage=None, metrics=None):
        self._storage = storage
        self._metrics = metrics
        self._start_time = time.monotonic()
        # V2：组件注册表
        self._components: dict[str, "ComponentCheck"] = {}

    def register_component(self, name: str, check_fn, critical: bool = True):
        """V2：注册组件检查函数

        Args:
            name: 组件名（如 "storage", "llm", "memory"）
            check_fn: 异步检查函数，返回 bool（True=健康）
            critical: 是否为关键组件（关键组件失败则整体不健康）
        """
        self._components[name] = ComponentCheck(name, check_fn, critical)

    def check(self) -> HealthStatus:
        """执行健康检查 — V1 同步版"""
        status = HealthStatus(
            uptime_seconds=time.monotonic() - self._start_time,
        )

        # 检查存储
        if self._storage:
            try:
                import asyncio
                count = asyncio.get_event_loop().run_until_complete(self._storage.count())
                status.memory_count = count
                status.components["storage"] = "ok"
            except Exception as e:
                status.ok = False
                status.last_error = str(e)
                status.components["storage"] = f"error: {e}"

        # 检查指标
        if self._metrics:
            try:
                summary = self._metrics.summary()
                status.components["metrics"] = "ok"
                status.components["counters"] = summary.get("_counters", {})
            except Exception as e:
                status.components["metrics"] = f"error: {e}"

        return status

    async def check_async(self) -> HealthStatus:
        """V2 异步健康检查（支持注册的组件）"""
        status = HealthStatus(
            uptime_seconds=time.monotonic() - self._start_time,
        )

        # 存储检查
        if self._storage:
            try:
                count = await self._storage.count()
                status.memory_count = count
                status.components["storage"] = "ok"
            except Exception as e:
                status.ok = False
                status.last_error = str(e)
                status.components["storage"] = f"error: {e}"

        # 指标检查
        if self._metrics:
            try:
                summary = self._metrics.summary()
                status.components["metrics"] = "ok"
                status.components["counters"] = summary.get("_counters", {})
            except Exception as e:
                status.components["metrics"] = f"error: {e}"

        # V2：注册的组件检查
        for name, comp in self._components.items():
            try:
                healthy = await comp.check_fn()
                if healthy:
                    status.components[name] = "ok"
                else:
                    status.components[name] = "unhealthy"
                    if comp.critical:
                        status.ok = False
                        status.last_error = f"Component '{name}' is unhealthy"
            except Exception as e:
                status.components[name] = f"error: {e}"
                if comp.critical:
                    status.ok = False
                    status.last_error = f"Component '{name}' error: {e}"

        return status


@dataclass
class ComponentCheck:
    """组件检查定义"""

    name: str
    check_fn: object  # Callable -> bool
    critical: bool = True


# ─────────────────────────────────────────────
# V2：结构化健康响应（用于 HTTP 端点）
# ─────────────────────────────────────────────

def health_response(status: HealthStatus, include_details: bool = True) -> dict:
    """生成标准健康检查响应"""
    resp = {
        "status": "healthy" if status.ok else "unhealthy",
        "uptime_seconds": round(status.uptime_seconds, 2),
    }
    if include_details:
        resp["components"] = status.components
        resp["memory_count"] = status.memory_count
        if status.last_error:
            resp["last_error"] = status.last_error
    return resp
