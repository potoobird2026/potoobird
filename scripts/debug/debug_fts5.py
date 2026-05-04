import asyncio
import os
import sqlite3
import tempfile


async def test():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, 'test.db')
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row

        # 建表和触发器
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                layer TEXT NOT NULL DEFAULT 'core',
                category TEXT NOT NULL DEFAULT 'general',
                source TEXT NOT NULL DEFAULT 'conversation',
                evidence TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                conflicts TEXT DEFAULT '[]',
                access_count INTEGER DEFAULT 0,
                zone TEXT DEFAULT 'warm',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content, tags,
                content='memories',
                content_rowid='rowid'
            );
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END;
        """)

        # 插入数据
        conn.execute(
            "INSERT INTO memories (id, content, layer, category, tags, zone, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ('test-1', 'Python 编程经验', 'core', 'test', '[]', 'warm', '2026-01-01Z', '2026-01-01Z')
        )
        conn.commit()

        # 检查主表
        row = conn.execute("SELECT rowid, content FROM memories WHERE id='test-1'").fetchone()
        print(f"主表: rowid={row['rowid']}, content={row['content']}")

        # 检查FTS表
        fts_rows = conn.execute("SELECT rowid, content FROM memories_fts").fetchall()
        print(f"FTS表行数: {len(fts_rows)}")
        for r in fts_rows:
            print(f"  FTS: rowid={r['rowid']}, content={r['content']}")

        # 尝试直接查询FTS
        try:
            fts_search = conn.execute("SELECT * FROM memories_fts WHERE memories_fts MATCH 'Python'").fetchall()
            print(f"FTS直接搜索: {len(fts_search)}")
        except Exception as e:
            print(f"FTS搜索错误: {e}")

        # 检查触发器
        triggers = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        print(f"触发器: {[t['name'] for t in triggers]}")

        conn.close()

asyncio.run(test())
