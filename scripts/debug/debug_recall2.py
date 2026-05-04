import asyncio
import os
import tempfile

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "test.db")
        s = SQLiteStorage(db)

        m = Memory(content="测试搜索内容", layer="core")
        r = await s.upsert(m)
        print(f"写入: id={r.id}, created={r.created}")

        rows = s.conn.execute("SELECT * FROM memories_fts").fetchall()
        print(f"FTS表数据: {rows}")

        results = await s.search("测试", layer="core")
        print(f"搜索结果: {len(results)} 条")

        rows2 = s.conn.execute(
            "SELECT * FROM memories_fts WHERE memories_fts MATCH ?", ("测试",)
        ).fetchall()
        print(f"直接FTS搜索: {rows2}")

        s.close()

asyncio.run(test())
