import os
import tempfile
from pathlib import Path

from src.audit.logger import AuditLogger
from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage

with tempfile.TemporaryDirectory() as d:
    content = (
        "# 人格配置\n\n"
        "| 维度 | 分值 | 说明 |\n"
        "|------|------|------|\n"
        "| H | 60 | 诚实-谦逊 |\n"
        "| E | 40 | 情绪性 |\n"
    )
    Path(d, "personality.md").write_text(content, encoding="utf-8")

    db = os.path.join(d, "test.db")
    storage = SQLiteStorage(db)
    audit = AuditLogger(os.path.join(d, "audit.jsonl"))

    # 先测试解析
    rows = MemoryManager._parse_markdown_table(Path(d, "personality.md"))
    print(f"解析结果: {rows}")

    mgr = MemoryManager(storage, d, audit_logger=audit)
    print(f"人格: {mgr.personality}")
    storage.close()
