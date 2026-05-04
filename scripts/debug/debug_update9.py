import asyncio
import os
import tempfile

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')

        # 第一次：创建全新数据库
        s = SQLiteStorage(db)

        # 检查 FTS 表创建方式
        fts_sql = s.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        ).fetchone()
        print(f'FTS 创建 SQL: {fts_sql[0] if fts_sql else "NOT FOUND"}')

        # 检查触发器
        trigger_sql = s.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='memories_ai'"
        ).fetchone()
        print(f'触发器 SQL: {trigger_sql[0] if trigger_sql else "NOT FOUND"}')

        # 写入
        m = Memory(content='Python 编程经验', layer='core', category='test')
        r = await s.upsert(m)
        print(f'写入: id={r.id}')

        # 检查 FTS 数据
        fts_data = s.conn.execute("SELECT * FROM memories_fts").fetchall()
        print(f'FTS 数据: {fts_data}')

        # UPDATE
        try:
            s.conn.execute("UPDATE memories SET access_count = access_count + ? WHERE id = ?", (10, r.id))
            s.conn.commit()
            print('UPDATE 成功')
        except Exception as e:
            print(f'UPDATE 失败: {e}')

        s.close()

        # 第二次：重新打开同一数据库
        print('\n--- 重新打开数据库 ---')
        s2 = SQLiteStorage(db)

        # 检查触发器
        trigger_sql2 = s2.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='memories_ai'"
        ).fetchone()
        print(f'触发器 SQL: {trigger_sql2[0] if trigger_sql2 else "NOT FOUND"}')

        # 检查 FTS
        fts_data2 = s2.conn.execute("SELECT * FROM memories_fts").fetchall()
        print(f'FTS 数据: {fts_data2}')

        # UPDATE
        try:
            s2.conn.execute("UPDATE memories SET access_count = access_count + ? WHERE id = ?", (10, r.id))
            s2.conn.commit()
            print('UPDATE 成功')
        except Exception as e:
            print(f'UPDATE 失败: {e}')

        s2.close()

asyncio.run(test())
