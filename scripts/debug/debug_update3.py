import asyncio
import os
import sqlite3
import tempfile


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')

        # 不用 SQLiteStorage，直接用 sqlite3 测试
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row

        # 不启用 WAL
        # conn.execute("PRAGMA journal_mode=WAL")

        conn.execute("""
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                layer TEXT NOT NULL DEFAULT 'core',
                access_count INTEGER DEFAULT 0,
                zone TEXT DEFAULT 'warm',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.execute(
            "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('test-1', 'Python', 'core', 0, 'warm', '2026-01-01Z', '2026-01-01Z')
        )
        conn.commit()

        # SELECT
        row = conn.execute("SELECT * FROM memories WHERE id='test-1'").fetchone()
        print(f'SELECT: access_count={row["access_count"]}')

        # UPDATE
        try:
            conn.execute("UPDATE memories SET access_count = access_count + ? WHERE id = ?", (10, 'test-1'))
            conn.commit()
            print('UPDATE 成功')
        except Exception as e:
            print(f'UPDATE 失败: {e}')

        # 再查
        row2 = conn.execute("SELECT * FROM memories WHERE id='test-1'").fetchone()
        print(f'更新后: access_count={row2["access_count"]}')

        conn.close()

asyncio.run(test())
