import asyncio
import os
import sqlite3
import tempfile


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row

        # 启用 WAL
        conn.execute("PRAGMA journal_mode=WAL")

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
            # 检查 WAL 状态
            try:
                wal_size = os.path.getsize(db + '-wal') if os.path.exists(db + '-wal') else 0
                shm_size = os.path.getsize(db + '-shm') if os.path.exists(db + '-shm') else 0
                print(f'WAL 文件大小: {wal_size} bytes')
                print(f'SHM 文件大小: {shm_size} bytes')
            except Exception as e2:
                print(f'检查 WAL 文件失败: {e2}')

        conn.close()

asyncio.run(test())
