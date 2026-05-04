"""
MCP 客户端数据模型

McpServerConfig  — 服务端配置
McpToolInfo      — 工具元数据
McpServerInfo    — 服务端运行时信息
McpResult        — 统一调用结果
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── 传输类型 ──────────────────────────────────────────────

class TransportType(enum.Enum):
    STDIO = "stdio"
    HTTP = "http"


# ── 服务端状态 ────────────────────────────────────────────

class ServerStatus(enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


# ── 服务端配置 ────────────────────────────────────────────

@dataclass
class McpServerConfig:
    """MCP 服务端配置（对应 mcp_servers 表一行）"""

    id: str                                          # 唯一标识
    name: str                                        # 显示名称
    transport: str = "stdio"                         # "stdio" | "http"
    # Stdio 专用
    command: str = ""                                # 可执行文件路径
    args: list[str] = field(default_factory=list)    # 命令行参数
    env: dict[str, str] = field(default_factory=dict)  # 环境变量
    # HTTP 专用
    url: str = ""                                    # 服务端 URL
    headers: dict[str, str] = field(default_factory=dict)  # 自定义请求头
    # 通用
    enabled: bool = True                             # 是否启用
    auto_connect: bool = True                        # 启动时自动连接
    timeout: float = 30.0                            # 调用超时（秒）
    # 元数据
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_row(self) -> dict[str, Any]:
        """序列化为 SQLite 行"""
        return {
            "id": self.id,
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self._json(self.args),
            "env": self._json(self.env),
            "url": self.url,
            "headers": self._json(self.headers),
            "enabled": int(self.enabled),
            "auto_connect": int(self.auto_connect),
            "timeout": self.timeout,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> McpServerConfig:
        """从 SQLite 行反序列化"""
        return cls(
            id=row["id"],
            name=row["name"],
            transport=row["transport"],
            command=row.get("command", ""),
            args=cls._parse_json(row.get("args", "[]"), []),
            env=cls._parse_json(row.get("env", "{}"), {}),
            url=row.get("url", ""),
            headers=cls._parse_json(row.get("headers", "{}"), {}),
            enabled=bool(row.get("enabled", 1)),
            auto_connect=bool(row.get("auto_connect", 1)),
            timeout=float(row.get("timeout", 30.0)),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    @staticmethod
    def _json(v: Any) -> str:
        import json
        return json.dumps(v, ensure_ascii=False)

    @staticmethod
    def _parse_json(v: Any, default: Any) -> Any:
        import json
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return default
        return v if v is not None else default


# ── 工具元数据 ────────────────────────────────────────────

@dataclass
class McpToolInfo:
    """MCP 工具元数据"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_id: str = ""

    def to_row(self) -> dict[str, Any]:
        import json
        return {
            "server_id": self.server_id,
            "tool_name": self.name,
            "description": self.description,
            "input_schema": json.dumps(self.input_schema, ensure_ascii=False),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> McpToolInfo:
        import json
        schema = {}
        raw = row.get("input_schema", "{}")
        if isinstance(raw, str):
            try:
                schema = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(
            name=row["tool_name"],
            description=row.get("description", ""),
            input_schema=schema,
            server_id=row["server_id"],
        )


# ── 服务端运行时信息 ──────────────────────────────────────

@dataclass
class McpServerInfo:
    """MCP 服务端运行时信息"""

    server_id: str
    status: str = "disconnected"
    protocol_version: str = ""
    server_name: str = ""
    server_version: str = ""
    tool_count: int = 0
    last_error: str = ""


# ── 统一调用结果 ──────────────────────────────────────────

@dataclass
class McpResult:
    """MCP 操作统一结果"""

    ok: bool
    content: str = ""
    error: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def success(content: str = "", **kwargs: Any) -> McpResult:
        return McpResult(ok=True, content=content, data=kwargs)

    @staticmethod
    def fail(error: str, **kwargs: Any) -> McpResult:
        return McpResult(ok=False, error=error, data=kwargs)

    @property
    def is_ok(self) -> bool:
        return self.ok

    @property
    def is_err(self) -> bool:
        return not self.ok
