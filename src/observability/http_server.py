"""
V2 可观测性 HTTP 端点

提供：
- GET /health  → 存活检查（始终 200，除非进程崩溃）
- GET /ready   → 就绪检查（存储、LLM、组件全部正常才 200）
- GET /metrics → Prometheus 格式指标

设计决策（ADR-010）：
- 使用 FastAPI（项目已依赖 pydantic，FastAPI 兼容）
- 独立 Router，不耦合主应用
- 端口通过配置外部化（默认 8001，避免与主应用冲突）
"""

import logging

logger = logging.getLogger("long_agent.observability.http")


def create_observability_router(
    health_checker=None,
    metrics_collector=None,
    readiness_checks: dict = None,
):
    """创建可观测性 Router

    Args:
        health_checker: HealthChecker 实例
        metrics_collector: MetricsCollector 实例（V2 Prometheus 接口）
        readiness_checks: 额外的就绪检查 {name: async_fn}

    Returns:
        FastAPI Router
    """
    try:
        from fastapi import APIRouter, Response
    except ImportError:
        logger.warning("FastAPI 未安装，HTTP 端点不可用。pip install fastapi uvicorn")
        return None

    router = APIRouter(tags=["observability"])

    @router.get("/health")
    async def health():
        """存活检查 — 始终返回 200（进程存活即健康）"""
        return {"status": "healthy", "service": "long-agent"}

    @router.get("/ready")
    async def ready():
        """就绪检查 — 所有依赖正常才返回 200"""
        if health_checker is None:
            return {"status": "ready", "service": "long-agent"}

        status = await health_checker.check_async()
        http_status = 200 if status.ok else 503
        body = {
            "status": "ready" if status.ok else "not_ready",
            "service": "long-agent",
            "uptime_seconds": round(status.uptime_seconds, 2),
            "components": status.components,
        }
        return Response(
            content=_json_dumps(body),
            status_code=http_status,
            media_type="application/json",
        )

    @router.get("/metrics")
    async def metrics():
        """Prometheus 格式指标"""
        if metrics_collector is None:
            return Response(
                content="# No metrics collector configured\n",
                media_type="text/plain",
            )

        prom = metrics_collector.prometheus_metrics()
        return Response(content=prom, media_type="text/plain; version=0.0.4")

    return router


def _json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def create_observability_app(
    health_checker=None,
    metrics_collector=None,
    title: str = "Long Agent Observability",
):
    """创建独立的可观测性 FastAPI 应用（用于单独启动）"""
    try:
        from fastapi import FastAPI
    except ImportError:
        logger.warning("FastAPI 未安装，无法创建 HTTP 端点")
        return None

    app = FastAPI(title=title, version="2.0.0")
    router = create_observability_router(health_checker, metrics_collector)
    if router:
        app.include_router(router)

    return app


async def start_observability_server(
    health_checker=None,
    metrics_collector=None,
    host: str = "0.0.0.0",
    port: int = 8001,
):
    """启动可观测性 HTTP 服务器（非阻塞）"""
    import uvicorn

    app = create_observability_app(health_checker, metrics_collector)
    if app is None:
        logger.error("无法启动可观测性服务器：FastAPI 未安装")
        return

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info(f"可观测性服务器启动：http://{host}:{port}")
    logger.info(f"  Health: http://{host}:{port}/health")
    logger.info(f"  Ready:  http://{host}:{port}/ready")
    logger.info(f"  Metrics: http://{host}:{port}/metrics")
    await server.serve()
