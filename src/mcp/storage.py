"""
MCP SQLite 持久化管理

管理两张表：
- mcp_servers     服务端配置
- mcp_tools_cache 工具缓存

提供 CRUD 操作，供 McpClient 在启动/连接/断开时调用。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.mcp.models import McpServerConfig, McpToolInfo

logger = logging.getLogger("long_agent.mcp.storage")

# ── 建表 SQL ──────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    transport TEXT NOT NULL CHECK(transport IN ('stdio', 'http')),
    command TEXT DEFAULT '',
    args TEXT DEFAULT '[]',
    env TEXT DEFAULT '{}',
    url TEXT DEFAULT '',
    headers TEXT DEFAULT '{}',
    enabled INTEGER DEFAULT 1,
    auto_connect INTEGER DEFAULT 1,
    timeout REAL DEFAULT 30.0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS mcp_tools_cache (
    server_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    description TEXT DEFAULT '',
    input_schema TEXT DEFAULT '{}',
    cached_at TEXT,
    PRIMARY KEY (server_id, tool_name),
    FOREIGN KEY (server_id) REFERENCES mcp_servers(id) ON DELETE CASCADE
);
"""


class McpStorage:
    """
    MCP SQLite 持久化存储

    线程安全说明：
    - 每个线程应创建独立的 McpStorage 实例
    - 或使用连接池
    - 此处使用 check_same_thread=False 允许多线程共享
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        """初始化数据库表结构"""
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        logger.debug(f"MCP 数据库已初始化: {self.db_path}")

    # ── 服务端 CRUD ────────────────────────────────────────

    def save_server(self, config: McpServerConfig) -> None:
        """插入或更新服务端配置"""
        now = datetime.now(timezone.utc).isoformat()
        config.updated_at = now
        if not config.created_at:
            config.created_at = now

        row = config.to_row()
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO mcp_servers
                (id, name, transport, command, args, env, url, headers,
                 enabled, auto_connect, timeout, created_at, updated_at)
            VALUES
                (:id, :name, :transport, :command, :args, :env, :url, :headers,
                 :enabled, :auto_connect, :timeout, :created_at, :updated_at)
            """,
            row,
        )
        conn.commit()
        logger.debug(f"服务端配置已保存: {config.id}")

    def load_server(self, server_id: str) -> McpServerConfig | None:
        """加载单个服务端配置"""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        if row is None:
            return None
        return McpServerConfig.from_row(dict(row))

    def load_all_servers(self) -> list[McpServerConfig]:
        """加载所有服务端配置"""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM mcp_servers").fetchall()
        return [McpServerConfig.from_row(dict(r)) for r in rows]

    def load_auto_connect_servers(self) -> list[McpServerConfig]:
        """加载所有 auto_connect=1 AND enabled=1 的服务端"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM mcp_servers WHERE auto_connect = 1 AND enabled = 1"
        ).fetchall()
        return [McpServerConfig.from_row(dict(r)) for r in rows]

    def delete_server(self, server_id: str) -> bool:
        """删除服务端配置（级联删除工具缓存）"""
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))
        conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            logger.debug(f"服务端配置已删除: {server_id}")
        return deleted

    # ── 工具缓存 CRUD ─────────────────────────────────────

    def save_tools(self, server_id: str, tools: list[McpToolInfo]) -> None:
        """批量保存工具缓存（先清空再插入）"""
        conn = self._get_conn()
        conn.execute("DELETE FROM mcp_tools_cache WHERE server_id = ?", (server_id,))
        for tool in tools:
            tool.server_id = server_id
            row = tool.to_row()
            conn.execute(
                """
                INSERT INTO mcp_tools_cache
                    (server_id, tool_name, description, input_schema, cached_at)
                VALUES
                    (:server_id, :tool_name, :description, :input_schema, :cached_at)
                """,
                row,
            )
        conn.commit()
        logger.debug(f"工具缓存已更新: {server_id} ({len(tools)} 个工具)")

    def load_tools(self, server_id: str) -> list[McpToolInfo]:
        """加载指定服务端的工具缓存"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM mcp_tools_cache WHERE server_id = ?", (server_id,)
        ).fetchall()
        return [McpToolInfo.from_row(dict(r)) for r in rows]

    def load_all_tools(self) -> list[McpToolInfo]:
        """加载所有工具缓存"""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM mcp_tools_cache").fetchall()
        return [McpToolInfo.from_row(dict(r)) for r in rows]

    def clear_tools(self, server_id: str) -> None:
        """清除指定服务端的工具缓存"""
        conn = self._get_conn()
        conn.execute("DELETE FROM mcp_tools_cache WHERE server_id = ?", (server_id,))
        conn.commit()

    # ── 生命周期 ───────────────────────────────────────────

    def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
