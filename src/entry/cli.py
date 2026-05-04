"""
CLI 入口 — typer

命令：
- run：交互模式
- once：执行单条命令
- audit show：查看审计日志
"""

import asyncio
import json
import logging

import typer

from src.config.settings import Settings, init_logging
from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage
from src.security.filter import InputFilter
from src.understanding.engine import UnderstandingEngine

logger = logging.getLogger("long_agent.cli")

app = typer.Typer(help="Long Agent — 以交付为核心的 AI 助手")
audit_app = typer.Typer(help="审计日志管理")
app.add_typer(audit_app, name="audit")
metrics_app = typer.Typer(help="可观测性指标")
app.add_typer(metrics_app, name="metrics")


def create_agent(read_only: bool = False):
    """创建 Agent 实例"""
    settings = Settings()
    init_logging(settings.log_level, settings.log_file)
    storage = SQLiteStorage(settings.database_path)
    memory = MemoryManager(storage, settings.data_dir, read_only=read_only)
    understanding = UnderstandingEngine()  # 理解层：意图解析 + 追问策略
    security = InputFilter()  # 安全层：5层纵深防御输入过滤

    # V2：创建 Agent 主循环
    # 注意：LLM Provider 需要 API Key，如果没有配置则不传入
    llm_provider = None
    try:
        if settings.openai_api_key:
            from src.llm.provider import OpenAIProvider

            llm_provider = OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
            )
            understanding_with_llm = UnderstandingEngine(llm_provider=llm_provider)
        else:
            understanding_with_llm = understanding
    except Exception as e:
        logger.warning(f"LLM Provider 初始化失败（降级为无 LLM 模式）: {e}")
        understanding_with_llm = understanding

    from pathlib import Path

    from src.background.manager import BackgroundTaskManager
    from src.context.compressor import BackgroundCompressor, ContextCompressor
    from src.delivery.report_generator import ReportGenerator
    from src.delivery.result_verifier import ResultVerifier
    from src.execution.b_supervisor import BSupervisor
    from src.execution.goal_anchor import GoalAnchor
    from src.execution.snapshot_manager import SnapshotManager
    from src.execution.sub_agent_manager import SubAgentManager
    from src.execution.tool_registry import ToolRegistry
    from src.llm.model_router import ModelRouter
    from src.llm.prompt_manager import PromptManager
    from src.loop.agent_loop import AgentLoop
    from src.mcp.client import McpClientManager as MCPClient
    from src.observability.health import HealthChecker
    from src.observability.metrics import MetricsCollector
    from src.personality.algorithms import PersonalityFusionEngine
    from src.security.guard import ApprovalModule, ConflictChecker, CredentialPool
    from src.session.event_bus import EventBus
    from src.session.session_manager import SessionManager
    from src.skill.manager import SkillRegistry as SkillManager

    context_window = 128000
    metrics = MetricsCollector()
    health_checker = HealthChecker(storage=storage, metrics=metrics)
    compressor = ContextCompressor(context_window=context_window)
    background_compressor = BackgroundCompressor(compressor=compressor)
    goal_anchor = GoalAnchor()
    snapshot_manager = SnapshotManager(snapshot_dir=str(Path(settings.data_dir) / "snapshots"))
    tool_registry = ToolRegistry()
    b_supervisor = BSupervisor(
        goal_anchor=goal_anchor,
        snapshot_manager=snapshot_manager,
        tool_registry=tool_registry,
    )
    subagent_manager = SubAgentManager(max_concurrent=3)
    result_verifier = ResultVerifier()
    report_generator = ReportGenerator()
    event_bus = EventBus()
    session_manager = SessionManager(
        memory_manager=memory,
        compressor=compressor,
        event_bus=event_bus,
        context_window=context_window,
    )
    background_manager = BackgroundTaskManager(data_dir=settings.data_dir)
    fusion_engine = PersonalityFusionEngine()
    approval_module = ApprovalModule()
    conflict_checker = ConflictChecker()
    credential_pool = CredentialPool()
    model_router = ModelRouter()
    prompt_manager = PromptManager()

    # Skill 系统
    skill_manager = SkillManager()
    try:
        skill_manager.load_all()
    except Exception as e:
        logger.warning(f"Skill 加载失败: {e}")

    # MCP Client（连接外部 MCP 服务器）
    mcp_client = MCPClient()

    agent_loop = AgentLoop(
        memory_manager=memory,
        understanding_engine=understanding_with_llm,
        llm_provider=llm_provider,
        tool_system=tool_registry,
        audit_logger=memory.audit,
        compressor=compressor,
        b_supervisor=b_supervisor,
        goal_anchor=goal_anchor,
        snapshot_manager=snapshot_manager,
        tool_registry=tool_registry,
        result_verifier=result_verifier,
        report_generator=report_generator,
        session_manager=session_manager,
        event_bus=event_bus,
        background_manager=background_manager,
        fusion_engine=fusion_engine,
        background_compressor=background_compressor,
        subagent_manager=subagent_manager,
        conflict_checker=conflict_checker,
        credential_pool=credential_pool,
        model_router=model_router,
        prompt_manager=prompt_manager,
        approval_module=approval_module,
    )

    return {
        "settings": settings,
        "memory": memory,
        "understanding": understanding_with_llm,
        "security": security,
        "agent_loop": agent_loop,
        "llm_provider": llm_provider,
        "read_only": read_only,
        "metrics": metrics,
        "health_checker": health_checker,
        "web_ui": True,
        "skill_manager": skill_manager,
        "mcp_client": mcp_client,
        "tool_registry": tool_registry,
    }


@app.command()
def web(
    host: str = "0.0.0.0",
    port: int = 8080,
    mcp_servers: list[str] = typer.Option(
        [], "--mcp", "-m", help="外部 MCP 服务器地址（可重复，如 http://localhost:9090/mcp）"
    ),
):
    """启动 Web UI（可选连接外部 MCP 服务器）"""
    import uvicorn

    agent = create_agent()
    if mcp_servers:
        mcp_client = agent["mcp_client"]
        for i, url in enumerate(mcp_servers):
            server_name = f"server_{i}"
            mcp_client.register_server(server_name, url)
            typer.echo(f"已注册 MCP 服务器: {server_name} ({url})")
        typer.echo(f"共注册 {len(mcp_servers)} 个外部 MCP 服务器，Web UI 启动后可通过 API 连接")
    uvicorn.run("src.entry.web_ui:app", host=host, port=port, reload=True)


@app.command()
def run(
    read_only: bool = typer.Option(
        False, "--read-only", "-r", help="只读模式：禁止写入记忆/修改配置"
    ),
    mcp_servers: list[str] = typer.Option(
        None, "--mcp", "-m", help="外部 MCP 服务器地址（如 http://localhost:9090/mcp）"
    ),
):
    """启动交互模式"""
    agent = create_agent(read_only=read_only)

    if read_only:
        typer.echo("⚠️  只读模式已启用：所有写入操作将被拒绝")

    # 注册外部 MCP 服务器
    if mcp_servers and isinstance(mcp_servers, list):
        mcp_client = agent["mcp_client"]
        for i, url in enumerate(mcp_servers):
            server_name = f"server_{i}"
            mcp_client.register_server(server_name, url)
        typer.echo(f"已注册 {len(mcp_servers)} 个外部 MCP 服务器")

    typer.echo("=" * 50)
    typer.echo("  Long Agent — 个人 AI 助手")
    typer.echo("  输入 '退出' 或按 Ctrl+C 结束")
    typer.echo("=" * 50)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while True:
            try:
                user_input = typer.prompt("\n你")
            except (EOFError, KeyboardInterrupt):
                break

            if user_input.strip() in ("退出", "exit", "quit", "q"):
                break

            if not user_input.strip():
                continue

            # 输入过滤（安全层）
            filter_result = agent["security"].filter(user_input)
            if not filter_result.is_ok:
                typer.echo(f"⚠️  输入被拒绝：{filter_result.error_message}")
                continue

            # V2：通过 Agent 主循环处理
            try:
                response = loop.run_until_complete(agent["agent_loop"].run(user_input))
                typer.echo(f"Agent: {response}")
            except Exception as e:
                logger.error(f"主循环处理失败: {e}", exc_info=True)
                typer.echo(f"❌ 处理失败：{e}")

    finally:
        agent["memory"].close()
        typer.echo("\n再见！")


@app.command()
def once(
    command: str = typer.Argument(..., help="要执行的命令"),
    read_only: bool = typer.Option(False, "--read-only", "-r"),
):
    """执行单条命令"""
    agent = create_agent(read_only=read_only)

    # 输入过滤（安全层）
    filter_result = agent["security"].filter(command)
    if not filter_result.is_ok:
        typer.echo(f"⚠️  输入被拒绝：{filter_result.error_message}")
        return

    # V2：通过 Agent 主循环处理
    try:
        loop = asyncio.new_event_loop()
        response = loop.run_until_complete(agent["agent_loop"].run(command))
        typer.echo(f"Agent: {response}")
    except Exception as e:
        logger.error(f"主循环处理失败: {e}", exc_info=True)
        typer.echo(f"❌ 处理失败：{e}")
    finally:
        agent["memory"].close()


@audit_app.command("show")
def audit_show(
    action: str = typer.Option(None, "--action", "-a", help="按操作类型过滤"),
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
):
    """查看审计日志"""
    from src.audit.logger import AuditAction

    agent = create_agent()
    action_enum = AuditAction(action) if action else None
    entries = agent["memory"].audit.query(action=action_enum, limit=limit)

    if not entries:
        typer.echo("暂无审计记录。")
        return

    for entry in entries:
        status = "✅" if entry["success"] else "❌"
        ts = entry["timestamp"][:19]
        typer.echo(
            f"{status} {ts} | {entry['action']:20s} | "
            f"{json.dumps(entry['details'], ensure_ascii=False)}"
        )

    agent["memory"].close()


# ── V2 可观测性命令 ──────────────────────────────


@metrics_app.command("show")
def metrics_show(
    format: str = typer.Option("text", "--format", "-f", help="输出格式：text / json"),
):
    """查看当前指标快照"""
    agent = create_agent()
    metrics = agent.get("metrics")
    if metrics is None:
        typer.echo("⚠️  指标采集器未初始化")
        return

    if format == "json":
        typer.echo(json.dumps(metrics.summary(), ensure_ascii=False, indent=2))
    else:
        summary = metrics.summary()
        typer.echo("═" * 50)
        typer.echo("  Long Agent — 指标快照")
        typer.echo("═" * 50)

        counters = summary.get("_counters", {})
        if counters:
            typer.echo("\n📊 计数器:")
            for k, v in sorted(counters.items()):
                typer.echo(f"  {k}: {v}")

        errors = summary.get("_errors", {})
        if errors:
            typer.echo("\n❌ 错误:")
            for k, v in sorted(errors.items()):
                typer.echo(f"  {k}: {v}")

        gauges = summary.get("_gauges", {})
        if gauges:
            typer.echo("\n📏 仪表盘:")
            for k, v in sorted(gauges.items()):
                typer.echo(f"  {k}: {v}")

        timings = {k: v for k, v in summary.items() if k not in ("_counters", "_errors", "_gauges")}
        if timings:
            typer.echo("\n⏱  耗时:")
            for k, v in sorted(timings.items()):
                if isinstance(v, dict):
                    typer.echo(
                        f"  {k}: count={v.get('count', 0)}, avg={v.get('avg_ms', 0):.1f}ms, max={v.get('max_ms', 0):.1f}ms"
                    )

        typer.echo("═" * 50)


@metrics_app.command("prometheus")
def metrics_prometheus():
    """输出 Prometheus 格式指标（供 Prometheus 采集）"""
    agent = create_agent()
    metrics = agent.get("metrics")
    if metrics is None:
        typer.echo("# No metrics collector configured")
        return
    typer.echo(metrics.prometheus_metrics())


@metrics_app.command("health")
def metrics_health():
    """执行健康检查"""
    agent = create_agent()
    health_checker = agent.get("health_checker")
    if health_checker is None:
        typer.echo("⚠️  健康检查器未初始化")
        return

    status = health_checker.check()
    icon = "✅" if status.ok else "❌"
    typer.echo(f"{icon} 健康状态: {'健康' if status.ok else '异常'}")
    typer.echo(f"  运行时间: {status.uptime_seconds:.1f}s")
    typer.echo(f"  记忆数量: {status.memory_count}")
    if status.components:
        typer.echo("  组件状态:")
        for name, state in sorted(status.components.items()):
            if isinstance(state, str):
                comp_icon = "✅" if state == "ok" else "⚠️"
                typer.echo(f"    {comp_icon} {name}: {state}")
    if status.last_error:
        typer.echo(f"  最后错误: {status.last_error}")

    agent["memory"].close()


if __name__ == "__main__":
    app()
