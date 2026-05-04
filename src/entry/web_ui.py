"""Web UI 入口 — FastAPI"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config.settings import Settings, init_logging
from src.loop.agent_loop import AgentLoop
from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage
from src.understanding.engine import UnderstandingEngine

logger = logging.getLogger("long_agent.web")

app = FastAPI(title="Long Agent", version="0.1.0")

BASE_DIR = Path(__file__).parent.parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_agent = None


def get_agent():
    global _agent
    if _agent is None:
        settings = Settings()
        init_logging(settings.log_level, settings.log_file)
        storage = SQLiteStorage(settings.database_path)
        memory = MemoryManager(storage, settings.data_dir)
        understanding = UnderstandingEngine()
        llm_provider = None
        if settings.openai_api_key:
            from src.llm.provider import OpenAIProvider

            llm_provider = OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
            )
        agent_loop = AgentLoop(
            memory_manager=memory,
            understanding_engine=understanding,
            llm_provider=llm_provider,
        )
        _agent = {"loop": agent_loop, "memory": memory, "settings": settings}
    return _agent


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    agent = get_agent()
    memory_count = await agent["memory"].storage.count()
    p = agent["memory"].personality
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "memory_count": memory_count,
            "personality": p,
        },
    )


@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    user_input = data.get("message", "")
    agent = get_agent()
    try:
        response = await agent["loop"].run(user_input)
        return {"response": response}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory")
async def get_memories(layer: str = None, limit: int = 50):
    agent = get_agent()
    memories = await agent["memory"].search("", layer=layer, limit=limit)
    return {"memories": [{"id": m.id, "content": m.content, "layer": m.layer} for m in memories]}


@app.post("/api/memory")
async def add_memory(request: Request):
    data = await request.json()
    agent = get_agent()
    result = await agent["memory"].remember(
        content=data.get("content", ""),
        layer=data.get("layer", "core"),
    )
    return {"id": result.id, "created": result.created}


@app.delete("/api/memory/{memory_id}")
async def delete_memory(memory_id: str):
    agent = get_agent()
    result = await agent["memory"].storage.delete(memory_id)
    return {"ok": result.is_ok}


@app.get("/api/personality")
async def get_personality():
    agent = get_agent()
    p = agent["memory"].personality
    return {
        "H": p.get("H", 50),
        "E": p.get("E", 50),
        "X": p.get("X", 50),
        "A": p.get("A", 50),
        "C": p.get("C", 50),
        "O": p.get("O", 50),
    }


@app.put("/api/personality")
async def update_personality(request: Request):
    data = await request.json()
    agent = get_agent()
    await agent["memory"].adjust_personality(data)
    return {"ok": True}


@app.get("/api/health")
async def health():
    agent = get_agent()
    return {"status": "ok", "memory_count": await agent["memory"].storage.count()}


@app.get("/api/skills")
async def list_skills():
    """列出所有 Skill"""
    try:
        from src.skill.manager import SkillManager

        sm = SkillManager()
        sm.load_all()
        return {"skills": sm.list_skills()}
    except Exception as e:
        return {"skills": [], "error": str(e)}


@app.get("/api/mcp/status")
async def mcp_status():
    """MCP Client 连接状态（已连接的外部服务器列表）"""
    try:
        agent = get_agent()
        mcp_client = agent.get("mcp_client")
        if mcp_client:
            return {
                "status": "ok",
                "mode": "client",
                "servers": mcp_client.get_servers(),
            }
        return {"status": "no_client", "servers": []}
    except Exception as e:
        return {"status": "error", "error": str(e), "servers": []}


@app.post("/api/mcp/connect")
async def mcp_connect(request: Request):
    """注册并连接外部 MCP 服务器"""
    data = await request.json()
    name = data.get("name", "")
    url = data.get("url", "")
    if not name or not url:
        return {"error": "需要提供 name 和 url"}, 400
    try:
        agent = get_agent()
        mcp_client = agent.get("mcp_client")
        if not mcp_client:
            return {"error": "MCP Client 未初始化"}, 500
        mcp_client.register_server(name, url)
        # 尝试连接
        import asyncio

        loop = asyncio.new_event_loop()
        failed = loop.run_until_complete(mcp_client.connect_all())
        loop.close()
        # 连接成功后注入工具到 ToolRegistry
        tool_registry = agent.get("tool_registry")
        if tool_registry:
            mcp_client.inject_to_tool_registry(tool_registry)
        return {
            "ok": True,
            "connected": name not in failed,
            "servers": mcp_client.get_servers(),
        }
    except Exception as e:
        return {"error": str(e)}, 500


@app.delete("/api/mcp/disconnect/{name}")
async def mcp_disconnect(name: str):
    """断开并移除外部 MCP 服务器"""
    try:
        agent = get_agent()
        mcp_client = agent.get("mcp_client")
        if not mcp_client:
            return {"error": "MCP Client 未初始化"}, 500
        mcp_client.remove_server(name)
        return {"ok": True, "servers": mcp_client.get_servers()}
    except Exception as e:
        return {"error": str(e)}, 500
