import asyncio
import os
import tempfile

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')
        s = SQLiteStorage(db)

        # 写入
        m = Memory(content='Python 编程经验', layer='core', category='test')
        r = await s.upsert(m)
        print(f'写入: id={r.id}')

        # 检查触发器
        triggers = s.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        print(f'触发器: {[t[0] for t in triggers]}')

        # 检查 FTS 表结构
        fts_cols = s.conn.execute("PRAGMA table_info(memories_fts)").fetchall()
        print(f'FTS 列: {[(c[1], c[2]) for c in fts_cols]}')

        # 检查 FTS 数据
        fts_data = s.conn.execute("SELECT * FROM memories_fts").fetchall()
        print(f'FTS 数据: {len(fts_data)} 行')

        # 检查主表数据
        rows = s.conn.execute("SELECT id, content, access_count FROM memories").fetchall()
        print(f'主表数据: {len(rows)} 行')
        for row in rows:
            print(f'  id={row[0][:8]}..., content={row[1][:20]}, access_count={row[2]}')

        # 尝试 UPDATE
        try:
            s.conn.execute("UPDATE memories SET access_count = COALESCE(access_count, 0) + ? WHERE id = ?", (10, r.id))
            s.conn.commit()
            print('UPDATE 成功')
        except Exception as e:
            print(f'UPDATE 失败: {type(e).__name__}: {e}')
            # 检查 sqlite 版本
            import sqlite3
            print(f'SQLite 版本: {sqlite3.sqlite_version}')
            print(f'Python sqlite3 版本: {sqlite3.version}')

        s.close()

asyncio.run(test())
