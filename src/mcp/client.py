"""
MCP 客户端 — stdio + HTTP 双传输 + SQLite 持久化 + 工具自动注册

完整 MCP 2024-11-05 协议实现。
"""

import asyncio
import json
import logging
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("long_agent.mcp")


# ========== 数据模型 ==========


@dataclass
class McpServerConfig:
    """MCP 服务器配置"""

    id: str = ""
    name: str = ""
    transport: str = "stdio"  # stdio / http / sse
    command: str = ""  # stdio 模式
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    url: str = ""  # HTTP 模式
    headers: dict = field(default_factory=dict)
    enabled: bool = True
    auto_connect: bool = False
    timeout: int = 30


@dataclass
class McpToolInfo:
    """MCP 工具信息"""

    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    server_id: str = ""


@dataclass
class McpServerInfo:
    """MCP 服务器信息"""

    name: str = ""
    version: str = ""
    protocol_version: str = ""
    capabilities: dict = field(default_factory=dict)


# ========== 传输层 ==========


class StdioMcpConnection:
    """stdio 模式 MCP 连接（subprocess + stdin/stdout JSON-RPC）"""

    def __init__(self, config: McpServerConfig):
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self):
        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**dict(subprocess.os.environ), **self.config.env} if self.config.env else None,
        )
        # asyncio 包装 pipe
        loop = asyncio.get_event_loop()
        self._reader = await asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        await loop.connect_read_pipe(lambda: protocol, self._process.stdout)
        self._writer = asyncio.StreamWriter(
            self._process.stdin, protocol=None, reader=None, loop=loop
        )

    async def send(self, message: dict) -> dict:
        """发送 JSON-RPC 请求，返回响应"""
        data = json.dumps(message, ensure_ascii=False) + "\n"
        self._writer.write(data.encode())
        await self._writer.drain()
        line = await asyncio.wait_for(self._reader.readline(), timeout=self.config.timeout)
        return json.loads(line.decode())

    async def close(self):
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()


class HttpMcpConnection:
    """HTTP 模式 MCP 连接（httpx + POST /mcp）"""

    def __init__(self, config: McpServerConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self):
        self._client = httpx.AsyncClient(
            timeout=self.config.timeout,
            headers=self.config.headers,
        )

    async def send(self, message: dict) -> dict:
        resp = await self._client.post(self.config.url, json=message)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        if self._client:
            await self._client.aclose()


# ========== 管理器 ==========


class McpClientManager:
    """
    MCP 客户端管理器

    核心 API：add_server / remove_server / connect / disconnect
             call_tool / list_servers / list_tools / get_server_status
    """

    DB_PATH = str(Path(__file__).parent.parent.parent / "data" / "mcp.db")

    # stdio 命令白名单
    SAFE_COMMANDS = {"npx", "node", "python", "python3", "deno", "bun"}

    def __init__(self, db_path: str = None):
        self._connections: dict[str, object] = {}
        self._tool_registry = None
        self._db_path = db_path or self.DB_PATH
        self._init_db()

    def _init_db(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id TEXT PRIMARY KEY, name TEXT, transport TEXT,
                    command TEXT, args TEXT, env TEXT,
                    url TEXT, headers TEXT,
                    enabled INTEGER, auto_connect INTEGER, timeout INTEGER,
                    installed_at TEXT, updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS mcp_tools_cache (
                    server_id TEXT, tool_name TEXT,
                    description TEXT, input_schema TEXT,
                    registered INTEGER DEFAULT 1,
                    PRIMARY KEY (server_id, tool_name)
                );
            """)

    def _save_server(self, config: McpServerConfig):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mcp_servers
                (id, name, transport, command, args, env, url, headers,
                 enabled, auto_connect, timeout, installed_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    config.id,
                    config.name,
                    config.transport,
                    config.command,
                    json.dumps(config.args),
                    json.dumps(config.env),
                    config.url,
                    json.dumps(config.headers),
                    int(config.enabled),
                    int(config.auto_connect),
                    config.timeout,
                    datetime.utcnow().isoformat(),
                    datetime.utcnow().isoformat(),
                ),
            )

    def _delete_server(self, server_id: str):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM mcp_servers WHERE id=?", (server_id,))
            conn.execute("DELETE FROM mcp_tools_cache WHERE server_id=?", (server_id,))

    def _load_servers(self) -> list[McpServerConfig]:
        servers = []
        with sqlite3.connect(self._db_path) as conn:
            for row in conn.execute("SELECT * FROM mcp_servers"):
                servers.append(
                    McpServerConfig(
                        id=row[0],
                        name=row[1],
                        transport=row[2],
                        command=row[3],
                        args=json.loads(row[4] or "[]"),
                        env=json.loads(row[5] or "{}"),
                        url=row[6] or "",
                        headers=json.loads(row[7] or "{}"),
                        enabled=bool(row[8]),
                        auto_connect=bool(row[9]),
                        timeout=row[10] or 30,
                    )
                )
        return servers

    def set_tool_registry(self, registry):
        self._tool_registry = registry

    # ========== 核心 API ==========

    def add_server(self, config: McpServerConfig) -> str:
        """添加服务器配置（持久化到 SQLite）"""
        if not config.id:
            config.id = config.name.lower().replace(" ", "_")
        self._save_server(config)
        logger.info(f"MCP 服务器已添加: {config.id} ({config.name})")
        return config.id

    def remove_server(self, server_id: str):
        """移除服务器（断开 + 删除配置 + 注销工具）"""
        asyncio.ensure_future(self.disconnect(server_id))
        self._delete_server(server_id)
        # 从 ToolRegistry 注销工具
        if self._tool_registry:
            try:
                self._tool_registry.unregister_by_prefix(f"mcp_{server_id}_")
            except Exception:
                pass
        logger.info(f"MCP 服务器已移除: {server_id}")

    async def connect(self, server_id: str) -> McpServerInfo:
        """连接服务器 → 握手 → 发现工具 → 注册到 ToolRegistry"""
        # 查找配置
        servers = self._load_servers()
        config = next((s for s in servers if s.id == server_id), None)
        if not config:
            raise ValueError(f"服务器未找到: {server_id}")

        # 创建连接
        if config.transport == "stdio":
            if config.command not in self.SAFE_COMMANDS:
                raise ValueError(f"命令不在白名单中: {config.command}")
            conn = StdioMcpConnection(config)
        elif config.transport in ("http", "sse"):
            conn = HttpMcpConnection(config)
        else:
            raise ValueError(f"不支持的传输方式: {config.transport}")

        await conn.connect()
        self._connections[server_id] = conn

        # initialize 握手
        init_resp = await conn.send(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "long-agent", "version": "0.1.0"},
                },
                "id": 1,
            }
        )
        server_info = McpServerInfo(
            name=init_resp.get("result", {}).get("serverInfo", {}).get("name", ""),
            version=init_resp.get("result", {}).get("serverInfo", {}).get("version", ""),
            protocol_version=init_resp.get("result", {}).get("protocolVersion", ""),
            capabilities=init_resp.get("result", {}).get("capabilities", {}),
        )

        # tools/list 发现工具
        tools_resp = await conn.send(
            {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "params": {},
                "id": 2,
            }
        )
        tools_data = tools_resp.get("result", {}).get("tools", [])
        tools = []
        for t in tools_data:
            tool = McpToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_id=server_id,
            )
            tools.append(tool)
            # 注册到 ToolRegistry
            if self._tool_registry:
                self._register_tool(server_id, tool)
            # 缓存到 SQLite
            self._cache_tool(server_id, tool)

        logger.info(f"MCP 已连接 [{server_id}]: {len(tools)} 个工具")
        return server_info

    def _register_tool(self, server_id: str, tool: McpToolInfo):
        """注册工具到 ToolRegistry"""
        from src.execution.tool_registry import ToolLevel

        tool_name = f"mcp_{server_id}_{tool.name}"
        self._tool_registry.register(
            name=tool_name,
            description=f"[MCP:{server_id}] {tool.description}",
            level=ToolLevel.L2_CONFIRM,
            handler=lambda params, sid=server_id, tn=tool.name: None,
        )

    def _cache_tool(self, server_id: str, tool: McpToolInfo):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO mcp_tools_cache
                (server_id, tool_name, description, input_schema, registered)
                VALUES (?,?,?,?,1)
            """,
                (
                    server_id,
                    tool.name,
                    tool.description,
                    json.dumps(tool.input_schema, ensure_ascii=False),
                ),
            )

    async def disconnect(self, server_id: str):
        """断开连接 + 注销工具"""
        conn = self._connections.pop(server_id, None)
        if conn:
            await conn.close()
        # 标记工具缓存为未注册
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("UPDATE mcp_tools_cache SET registered=0 WHERE server_id=?", (server_id,))

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict = None) -> str:
        """调用 MCP 工具"""
        conn = self._connections.get(server_id)
        if not conn:
            raise ValueError(f"服务器未连接: {server_id}")
        resp = await conn.send(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments or {}},
                "id": 1,
            }
        )
        if "error" in resp:
            raise RuntimeError(f"MCP 错误: {resp['error'].get('message', '未知')}")
        content = resp.get("result", {}).get("content", [])
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

    # ========== 查询 API ==========

    def list_servers(self) -> list[dict]:
        return [
            {
                "id": s.id,
                "name": s.name,
                "transport": s.transport,
                "enabled": s.enabled,
                "connected": s.id in self._connections,
            }
            for s in self._load_servers()
        ]

    def list_tools(self, server_id: str = None) -> list[McpToolInfo]:
        tools = []
        with sqlite3.connect(self._db_path) as conn:
            for row in conn.execute(
                "SELECT server_id, tool_name, description, input_schema FROM mcp_tools_cache"
                + (" WHERE server_id=?" if server_id else ""),
                (server_id,) if server_id else (),
            ):
                tools.append(
                    McpToolInfo(
                        name=row[1],
                        description=row[2] or "",
                        input_schema=json.loads(row[3] or "{}"),
                        server_id=row[0],
                    )
                )
        return tools

    def get_server_status(self, server_id: str) -> dict:
        connected = server_id in self._connections
        tools = self.list_tools(server_id)
        return {
            "id": server_id,
            "connected": connected,
            "tools_count": len(tools),
            "tools": [{"name": t.name, "description": t.description} for t in tools],
        }
