import asyncio
import os
import tempfile

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "test.db")
        s = SQLiteStorage(db)

        m = Memory(content="Python programming", layer="core")
        r = await s.upsert(m)
        print(f"写入: id={r.id}")

        # 查看 FTS 表结构和数据
        cols = s.conn.execute("PRAGMA table_info(memories_fts)").fetchall()
        print(f"FTS列: {[dict(c) for c in cols]}")

        rows = s.conn.execute("SELECT * FROM memories_fts").fetchall()
        for row in rows:
            print(f"FTS行: {dict(row)}")

        # 主表数据
        main = s.conn.execute("SELECT id, content, tags FROM memories").fetchall()
        for row in main:
            print(f"主表行: {dict(row)}")

        # 直接 FTS 搜索
        try:
            rows2 = s.conn.execute(
                "SELECT * FROM memories_fts WHERE memories_fts MATCH ?", ("Python",)
            ).fetchall()
            print(f"FTS搜索Python: {[dict(r) for r in rows2]}")
        except Exception as e:
            print(f"FTS搜索错误: {e}")

        # 测试不带 layer 搜索
        results = await s.search("Python")
        print(f"search(无layer): {len(results)} 条")

        s.close()

asyncio.run(test())
