import asyncio
import os
import tempfile

from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')
        s = SQLiteStorage(db)

        # 检查 FTS 表结构
        fts_cols = s.conn.execute("PRAGMA table_info(memories_fts)").fetchall()
        print(f'memories_fts 列: {[(c["name"], c["type"]) for c in fts_cols]}')

        # 检查触发器 SQL
        triggers = s.conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        for t in triggers:
            print(f'触发器 {t["name"]}: {t["sql"][:200]}')

        # 尝试手动触发：直接 INSERT 一条记录
        import uuid
        mid = str(uuid.uuid4())
        try:
            s.conn.execute(
                "INSERT INTO memories (id, content, layer, category, source, evidence, tags, conflicts, access_count, zone, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, '手动测试', 'core', 'test', 'test', '', '[]', '[]', 0, 'warm', '2026-01-01Z', '2026-01-01Z')
            )
            s.conn.commit()
            print(f'手动 INSERT 成功: {mid}')
        except Exception as e:
            print(f'手动 INSERT 失败: {e}')

        # 检查 FTS 表数据
        fts_data = s.conn.execute("SELECT * FROM memories_fts").fetchall()
        print(f'FTS 表数据: {len(fts_data)} 行')
        for row in fts_data:
            print(f'  rowid={row[0]}, content={row[1] if len(row) > 1 else "N/A"}')

        s.close()

asyncio.run(test())
