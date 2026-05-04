import asyncio
import os
import tempfile

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')

        # 创建数据库
        s = SQLiteStorage(db)

        # 检查 FTS 表是否存在
        fts = s.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        ).fetchone()
        print(f'FTS 表存在: {fts is not None}')

        # 检查 FTS 表数据
        fts_count = s.conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
        print(f'FTS 表行数: {fts_count}')

        # 写入
        m = Memory(content='Python 编程经验', layer='core', category='test')
        r = await s.upsert(m)
        print(f'写入: id={r.id}')

        # 写入后 FTS 数据
        fts_count2 = s.conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
        print(f'写入后 FTS 行数: {fts_count2}')

        # 尝试 UPDATE
        try:
            s.conn.execute("UPDATE memories SET access_count = COALESCE(access_count, 0) + ? WHERE id = ?", (10, r.id))
            s.conn.commit()
            print('UPDATE 成功')
        except Exception as e:
            print(f'UPDATE 失败: {e}')
            # 检查 FTS 表是否损坏
            try:
                s.conn.execute("SELECT * FROM memories_fts")
                print('FTS 表可读')
            except Exception as e2:
                print(f'FTS 表损坏: {e2}')

        s.close()

asyncio.run(test())
