import os
import sqlite3
import tempfile

with tempfile.TemporaryDirectory() as d:
    db = os.path.join(d, 'test.db')
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")

    # 建主表
    conn.execute("""
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            access_count INTEGER DEFAULT 0
        )
    """)

    # 建 FTS 表（含 memory_id）
    conn.execute("""
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            memory_id UNINDEXED, content, tags
        )
    """)

    # 建触发器
    conn.execute("""
        CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(memory_id, content, tags)
            VALUES (new.id, new.content, '[]');
        END;
    """)

    # 插入
    conn.execute("INSERT INTO memories VALUES (?, ?, ?)", ('test-1', 'Python 编程', 0))
    conn.commit()

    # 检查
    row = conn.execute("SELECT * FROM memories WHERE id='test-1'").fetchone()
    print(f'主表: {row}')

    fts = conn.execute("SELECT * FROM memories_fts").fetchall()
    print(f'FTS: {fts}')

    # UPDATE
    try:
        conn.execute("UPDATE memories SET access_count = access_count + ? WHERE id = ?", (10, 'test-1'))
        conn.commit()
        print('UPDATE 成功')
    except Exception as e:
        print(f'UPDATE 失败: {e}')

    conn.close()
