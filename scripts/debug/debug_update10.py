import os
import sqlite3
import tempfile

with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, 'test.db')
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            access_count INTEGER DEFAULT 0
        )
    """)

    # 方案A：FTS 表只用 content，不用 memory_id
    conn.execute("CREATE VIRTUAL TABLE memories_fts USING fts5(content)")

    # 触发器：只插入 content
    conn.execute("""
        CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(content) VALUES (new.content);
        END;
    """)

    conn.execute("INSERT INTO memories VALUES (?, ?, ?)", ('test-1', 'Python 编程', 0))
    conn.commit()

    # UPDATE
    try:
        conn.execute("UPDATE memories SET access_count = access_count + ? WHERE id = ?", (10, 'test-1'))
        conn.commit()
        print('方案A UPDATE 成功')
    except Exception as e:
        print(f'方案A UPDATE 失败: {e}')

    conn.close()
