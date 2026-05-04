import asyncio
import os
import tempfile

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')
        s = SQLiteStorage(db)

        # 检查 WAL 模式
        wal_mode = s.conn.execute("PRAGMA journal_mode").fetchone()[0]
        print(f'journal_mode: {wal_mode}')

        # 检查表结构
        cols = s.conn.execute("PRAGMA table_info(memories)").fetchall()
        print(f'memories 表列: {[(c["name"], c["type"]) for c in cols]}')

        # 写入
        m = Memory(content='Python 编程经验', layer='core', category='test')
        r = await s.upsert(m)
        print(f'写入: id={r.id}')

        # 直接查数据库
        row = s.conn.execute("SELECT id, content, access_count FROM memories WHERE id=?", (r.id,)).fetchone()
        print(f'直接查: id={row["id"]}, access_count={row["access_count"]}, type={type(row["access_count"])}')

        # 尝试 UPDATE
        try:
            s.conn.execute("UPDATE memories SET access_count = access_count + ? WHERE id = ?", (10, r.id))
            s.conn.commit()
            print('UPDATE 成功')
        except Exception as e:
            print(f'UPDATE 失败: {type(e).__name__}: {e}')
            # 检查是否有触发器干扰
            triggers = s.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
            print(f'触发器: {[t["name"] for t in triggers]}')
            # 检查 FTS 表
            fts = s.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'").fetchall()
            print(f'FTS 表: {[f["name"] for f in fts]}')

        s.close()

asyncio.run(test())
