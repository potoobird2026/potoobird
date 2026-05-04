"""
性能基准测试 — V1

验证关键操作的性能指标：
- 写入：< 50ms
- 读取：< 10ms
- 搜索：< 100ms
- 备份：< 500ms
"""

import asyncio
import os
import tempfile
import time

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


def benchmark(func):
    """计时装饰器"""

    async def wrapper(*args, **kwargs):
        start = time.monotonic()
        result = await func(*args, **kwargs)
        elapsed_ms = (time.monotonic() - start) * 1000
        return result, elapsed_ms

    return wrapper


async def run_benchmarks():
    print("=" * 60)
    print("  Long Agent V1 性能基准")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "bench.db")
        s = SQLiteStorage(db)

        # ---- 写入性能 ----
        times = []
        for i in range(100):
            m = Memory(content=f"基准测试记忆 {i}", layer="core")
            start = time.monotonic()
            await s.upsert(m)
            times.append((time.monotonic() - start) * 1000)

        avg_write = sum(times) / len(times)
        max_write = max(times)
        print(f"\n[写入] 100次平均: {avg_write:.2f}ms, 最大: {max_write:.2f}ms")
        print(f"       {'PASS' if avg_write < 50 else 'FAIL'} (目标: <50ms)")

        # ---- 读取性能 ----
        rows = s.conn.execute("SELECT id FROM memories LIMIT 100").fetchall()
        ids = [r[0] for r in rows]

        times = []
        for mid in ids:
            start = time.monotonic()
            await s.get(mid)
            times.append((time.monotonic() - start) * 1000)

        avg_read = sum(times) / len(times)
        print(f"\n[读取] 100次平均: {avg_read:.2f}ms")
        print(f"       {'PASS' if avg_read < 10 else 'FAIL'} (目标: <10ms)")

        # ---- 搜索性能 ----
        times = []
        queries = ["基准", "测试", "记忆", "不存在"]
        for q in queries:
            start = time.monotonic()
            await s.search(q, layer="core")
            times.append((time.monotonic() - start) * 1000)

        avg_search = sum(times) / len(times)
        print(f"\n[搜索] {len(queries)}次平均: {avg_search:.2f}ms")
        print(f"       {'PASS' if avg_search < 100 else 'FAIL'} (目标: <100ms)")

        # ---- 备份性能 ----
        backup_dir = os.path.join(d, "backups")
        start = time.monotonic()
        s.backup(backup_dir)
        backup_ms = (time.monotonic() - start) * 1000
        print(f"\n[备份] {backup_ms:.2f}ms")
        print(f"       {'PASS' if backup_ms < 500 else 'FAIL'} (目标: <500ms)")

        s.close()

    print("\n" + "=" * 60)
    print("  基准测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_benchmarks())
