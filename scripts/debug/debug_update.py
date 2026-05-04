import asyncio
import os
import sqlite3
import tempfile


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")

        # 建表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                layer TEXT NOT NULL DEFAULT 'core',
                access_count INTEGER DEFAULT 0,
                zone TEXT DEFAULT 'warm',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 插入
        conn.execute(
            "INSERT INTO memories (id, content, layer, access_count, zone, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('test-1', 'Python 编程经验', 'core', 0, 'warm', '2026-01-01Z', '2026-01-01Z')
        )
        conn.commit()

        # 查询
        row = conn.execute("SELECT * FROM memories WHERE id='test-1'").fetchone()
        print(f"查询结果: id={row['id']}, access_count={row['access_count']}, type={type(row['access_count'])}")

        # 尝试 UPDATE
        try:
            conn.execute("UPDATE memories SET access_count = COALESCE(access_count, 0) + ? WHERE id = ?", (10, 'test-1'))
            conn.commit()
            print("UPDATE 成功")
        except Exception as e:
            print(f"UPDATE 失败: {e}")

        # 再查
        row2 = conn.execute("SELECT * FROM memories WHERE id='test-1'").fetchone()
        print(f"更新后: access_count={row2['access_count']}")

        conn.close()

asyncio.run(test())
