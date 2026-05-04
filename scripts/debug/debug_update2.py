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

        # 读取
        got = await s.get(r.id)
        print(f'读取: content={got.content}')

        # 精确匹配
        found = await s.find_by_content('Python 编程经验', layer='core')
        print(f'精确匹配: {found is not None}')

        # 计数
        count = await s.count(layer='core')
        print(f'计数: {count}')

        # update_access_count
        try:
            await s.update_access_count(r.id, delta=10)
            print('update_access_count 成功')
        except Exception as e:
            print(f'update_access_count 失败: {type(e).__name__}: {e}')
            # 尝试直接执行
            try:
                s.conn.execute("UPDATE memories SET access_count = COALESCE(access_count, 0) + ? WHERE id = ?", (10, r.id))
                s.conn.commit()
                print('直接 UPDATE 成功')
            except Exception as e2:
                print(f'直接 UPDATE 也失败: {e2}')

        s.close()

asyncio.run(test())
