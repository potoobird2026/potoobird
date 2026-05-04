"""
SQLite 存储实现 — MVP

特性：
- WAL 模式（并发读写不锁表）
- FTS5 全文搜索
- 跨平台文件权限（Linux/macOS chmod / Windows icacls）
- 在线备份（不锁表）
- 幂等性支持（find_by_content 精确匹配）
"""

import json
import logging
import os
import platform
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.errors.types import ErrorCode, OperationResult

from .base import BatchWriteResult, Memory, MemoryStorage, MemoryWriteResult, Snapshot

logger = logging.getLogger("long_agent.storage.sqlite")

# 建表 SQL
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    layer TEXT NOT NULL DEFAULT 'core',
    category TEXT NOT NULL DEFAULT 'general',
    source TEXT NOT NULL DEFAULT 'conversation',
    evidence TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    conflicts TEXT DEFAULT '[]',
    access_count INTEGER DEFAULT 0,
    zone TEXT DEFAULT 'warm',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_layer ON memories(layer);
CREATE INDEX IF NOT EXISTS idx_memories_zone ON memories(zone);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at);

-- FTS5 全文搜索虚拟表
-- memory_id 是普通列（不是 UNINDEXED），用于触发器精确定位
-- 搜索时 JOIN 主表过滤 layer/zone
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    tags,
    memory_id UNINDEXED
);

-- 触发器：FTS 表与主表同步（使用 memory_id 精确定位，避免 content 重复误删）
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(content, tags, memory_id)
    VALUES (new.content, new.tags, new.id);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.id;
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    DELETE FROM memories_fts WHERE memory_id = old.id;
    INSERT INTO memories_fts(content, tags, memory_id)
    VALUES (new.content, new.tags, new.id);
END;

-- 快照表
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- 用户对话模式表（context_compressor 持久化用）
CREATE TABLE IF NOT EXISTS user_dialogue_model (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avg_message_length REAL,
    question_ratio REAL,
    topic_switch_frequency REAL,
    detail_level TEXT,
    updated_at TEXT NOT NULL
);

-- Schema 版本管理
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""


class SQLiteStorage(MemoryStorage):
    """SQLite 存储实现 — MVP（跨平台）"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()

        # 设置数据库文件权限（跨平台）
        self._set_file_permission(db_path)

    # ---- 跨平台文件权限 ----

    @staticmethod
    def _set_file_permission(path: str):
        """设置文件为仅当前用户可读写（跨平台）"""
        system = platform.system()
        try:
            if system in ("Linux", "Darwin"):
                os.chmod(path, 0o600)
            elif system == "Windows":
                subprocess.run(["icacls", path, "/reset", "/Q"], capture_output=True, timeout=10)
                subprocess.run(
                    ["icacls", path, "/grant", f"{os.getlogin()}:F", "/Q"],
                    capture_output=True,
                    timeout=10,
                )
                subprocess.run(
                    ["icacls", path, "/inheritance:r", "/Q"], capture_output=True, timeout=10
                )
            else:
                logger.warning(f"未知操作系统 {system}，跳过文件权限设置: {path}")
        except Exception as e:
            logger.warning(
                f"设置文件权限失败（{system}）: {path} — {e}。请手动确保该文件不被其他用户访问。"
            )

    # ---- 初始化 ----

    def _init_tables(self):
        """建表（幂等，重复执行安全）"""
        # 先删除旧触发器和 FTS 表（避免旧版本残留）
        for name in ("memories_ai", "memories_ad", "memories_au"):
            self.conn.execute(f"DROP TRIGGER IF EXISTS {name}")
        self.conn.execute("DROP TABLE IF EXISTS memories_fts")
        # 重建所有表和触发器
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    # ---- 工具方法 ----

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        """数据库行 → Memory 对象"""
        return Memory(
            id=row["id"],
            content=row["content"],
            layer=row["layer"],
            category=row["category"],
            source=row["source"],
            evidence=row["evidence"],
            tags=json.loads(row["tags"]),
            conflicts=json.loads(row["conflicts"]),
            access_count=row["access_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _generate_id(self) -> str:
        """生成唯一 ID"""
        import uuid

        return str(uuid.uuid4())

    # ---- 核心 CRUD（async 包装） ----

    async def get(self, memory_id: str) -> Optional[Memory]:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._row_to_memory(row) if row else None

    async def find_by_content(self, content: str, layer: str = None) -> Optional[Memory]:
        """精确匹配内容（幂等性检查用）"""
        if layer:
            row = self.conn.execute(
                "SELECT * FROM memories WHERE content = ? AND layer = ? LIMIT 1", (content, layer)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM memories WHERE content = ? LIMIT 1", (content,)
            ).fetchone()
        return self._row_to_memory(row) if row else None

    async def search(self, query: str, layer: str = None, limit: int = 10) -> list[Memory]:
        """
        全文搜索

        策略：
        - 英文/关键词 → FTS5（MATCH，支持 rank 排序）
        - 中文 → LIKE（FTS5 默认 tokenizer 不支持中文分词）
        - V2 可升级为 trigram tokenizer 或外部搜索引擎
        """
        if not query:
            # 空查询 → 返回最近更新的
            if layer:
                rows = self.conn.execute(
                    "SELECT * FROM memories WHERE layer = ? ORDER BY updated_at DESC LIMIT ?",
                    (layer, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        elif any("\u4e00" <= c <= "\u9fff" for c in query):
            # 含中文 → LIKE 搜索（FTS5 默认 unicode61 tokenizer 不支持中文分词）
            pattern = f"%{query}%"
            if layer:
                rows = self.conn.execute(
                    "SELECT * FROM memories "
                    "WHERE content LIKE ? AND layer = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (pattern, layer, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM memories WHERE content LIKE ? ORDER BY updated_at DESC LIMIT ?",
                    (pattern, limit),
                ).fetchall()
        else:
            # 纯英文/关键词 → FTS5 MATCH
            if layer:
                rows = self.conn.execute(
                    """SELECT m.* FROM memories m
                       INNER JOIN memories_fts f ON m.id = f.memory_id
                       WHERE memories_fts MATCH ? AND m.layer = ?
                       ORDER BY f.rank LIMIT ?""",
                    (query, layer, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """SELECT m.* FROM memories m
                       INNER JOIN memories_fts f ON m.id = f.memory_id
                       WHERE memories_fts MATCH ?
                       ORDER BY f.rank LIMIT ?""",
                    (query, limit),
                ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def upsert(self, memory: Memory) -> MemoryWriteResult:
        """写入或更新记忆"""
        now = datetime.now(timezone.utc).isoformat() + "Z"

        if not memory.id:
            memory.id = self._generate_id()
            memory.created_at = now
        memory.updated_at = now

        self.conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, content, layer, category, source, evidence, tags,
                conflicts, access_count, zone, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.content,
                memory.layer,
                memory.category,
                memory.source,
                memory.evidence,
                json.dumps(memory.tags),
                json.dumps(memory.conflicts),
                memory.access_count,
                "warm",
                memory.created_at,
                memory.updated_at,
            ),
        )
        self.conn.commit()

        return MemoryWriteResult(id=memory.id, created=True)

    async def delete(self, memory_id: str) -> OperationResult:
        """删除记忆，返回 OperationResult"""
        try:
            cursor = self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self.conn.commit()
            if cursor.rowcount == 0:
                return OperationResult.fail(
                    code=ErrorCode.NOT_FOUND,
                    message=f"记忆不存在: {memory_id}",
                )
            return OperationResult.success(deleted_id=memory_id)
        except Exception as e:
            logger.error(f"删除记忆失败: {memory_id} — {e}")
            return OperationResult.fail(
                code=ErrorCode.UNKNOWN,
                message=f"删除失败: {e}",
            )

    async def count(self, layer: str = None) -> int:
        if layer:
            result = self.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE layer = ?", (layer,)
            ).fetchone()[0]
        else:
            result = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return result

    # ---- 批量操作 ----

    async def batch_upsert(self, memories: list[Memory]) -> BatchWriteResult:
        result = BatchWriteResult()
        for mem in memories:
            try:
                await self.upsert(mem)
                result.success_count += 1
            except Exception as e:
                result.failed_count += 1
                result.failed_ids.append(mem.id)
                result.errors.append(str(e))
        return result

    async def batch_get(self, memory_ids: list[str]) -> list[Memory]:
        if not memory_ids:
            return []
        result = []
        for mid in memory_ids:
            row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (mid,)).fetchone()
            if row:
                result.append(self._row_to_memory(row))
        return result

    async def batch_update_access_counts(self, updates: dict[str, int]):
        for memory_id, delta in updates.items():
            self.conn.execute(
                "UPDATE memories SET access_count = COALESCE(access_count, 0) + ? WHERE id = ?",
                (delta, memory_id),
            )
        self.conn.commit()

    # ---- 热/冷区管理 ----

    async def get_by_zone(self, zone: str, limit: int = 100) -> list[Memory]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE zone = ? ORDER BY access_count DESC LIMIT ?",
            (zone, limit),
        ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    async def update_access_count(self, memory_id: str, delta: int = 1):
        self.conn.execute(
            "UPDATE memories SET access_count = COALESCE(access_count, 0) + ? WHERE id = ?",
            (delta, memory_id),
        )
        self.conn.commit()

    async def decay_all_access_counts(self, factor: float = 0.9):
        """访问计数衰减"""
        self.conn.execute(
            "UPDATE memories SET access_count = CAST(COALESCE(access_count, 0) * ? AS INTEGER)",
            (factor,),
        )
        self.conn.commit()

    # ---- 快照 ----

    async def get_old_snapshots(self, days: int = 7) -> list[Snapshot]:
        rows = self.conn.execute(
            "SELECT * FROM snapshots WHERE created_at < datetime('now', ?)", (f"-{days} days",)
        ).fetchall()
        results = []
        for row in rows:
            results.append(
                Snapshot(
                    id=row["id"],
                    task_id=row["task_id"],
                    state=json.loads(row["state"]),
                    created_at=row["created_at"],
                )
            )
        return results

    async def delete_snapshots(self, snapshot_ids: list[str]):
        if not snapshot_ids:
            return
        for sid in snapshot_ids:
            self.conn.execute("DELETE FROM snapshots WHERE id = ?", (sid,))
        self.conn.commit()

    # ---- 维护 ----

    async def vacuum(self):
        """回收空间、优化数据库"""
        self.conn.execute("VACUUM")

    def backup(self, backup_dir: str = "data/backups", keep: int = 3) -> str:
        """
        SQLite 在线备份（不锁表）

        使用 sqlite3 的 backup API，读写都不中断。
        """
        backup_path = Path(backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = backup_path / f"memory_{timestamp}.db"

        # 在线备份
        dest = sqlite3.connect(str(dest_path))
        self.conn.backup(dest)
        dest.close()

        # 设置备份文件权限
        self._set_file_permission(str(dest_path))

        # 清理旧备份
        backups = sorted(backup_path.glob("memory_*.db"))
        for old_backup in backups[:-keep]:
            old_backup.unlink()
            logger.info(f"清理旧备份: {old_backup.name}")

        logger.info(f"备份完成: {dest_path}")
        return str(dest_path)

    def close(self):
        if self.conn:
            self.conn.close()

    # ---- 事务支持 ----

    async def begin_transaction(self):
        self.conn.execute("BEGIN")

    async def commit(self):
        self.conn.commit()

    async def rollback(self):
        self.conn.rollback()
