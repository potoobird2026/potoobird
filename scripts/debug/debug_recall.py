import asyncio
import os
import tempfile

from src.audit.logger import AuditLogger
from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(d, 'audit.jsonl'))
        mgr = MemoryManager(storage, d, audit_logger=audit)

        r = await mgr.remember('测试记忆内容', layer='core')
        print(f'写入: created={r.created}, id={r.id}')

        # 直接查数据库
        count = await storage.count(layer='core')
        print(f'core层总数: {count}')

        # FTS5 搜索
        results = await storage.search('测试', layer='core')
        print(f'FTS5搜索结果: {len(results)}')
        for r in results:
            print(f'  - [{r.id}] {r.content}')

        # 空查询（返回最近更新）
        results2 = await storage.search('', layer='core')
        print(f'空查询结果: {len(results2)}')

        storage.close()

asyncio.run(test())
