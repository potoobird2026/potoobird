import asyncio
import os
import tempfile

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "test.db")
        s = SQLiteStorage(db)

        # 中文内容
        m = Memory(content="测试搜索内容", layer="core")
        r = await s.upsert(m)

        # 直接 FTS 搜索中文
        try:
            rows = s.conn.execute(
                "SELECT * FROM memories_fts WHERE memories_fts MATCH ?", ("测试",)
            ).fetchall()
            print(f"FTS搜索'测试': {[dict(r) for r in rows]}")
        except Exception as e:
            print(f"FTS中文搜索错误: {e}")

        # FTS 默认 tokenizer 不支持中文分词，试试前缀搜索
        try:
            rows2 = s.conn.execute(
                "SELECT * FROM memories_fts WHERE memories_fts MATCH ?", ("测试*",)
            ).fetchall()
            print(f"FTS前缀搜索'测试*': {[dict(r) for r in rows2]}")
        except Exception as e:
            print(f"前缀搜索错误: {e}")

        # 用 LIKE 替代
        rows3 = s.conn.execute(
            "SELECT * FROM memories WHERE content LIKE ?", ("%测试%",)
        ).fetchall()
        print(f"LIKE搜索: {len(rows3)} 条")

        s.close()

asyncio.run(test())
