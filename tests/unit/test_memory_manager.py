"""
单元测试 — MemoryManager

人格 key：H/E/X/A/C/O（HEXACO 单字母）
"""

import os
import tempfile

import pytest

from src.audit.logger import AuditAction, AuditLogger
from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def manager(tmp_dir):
    db = os.path.join(tmp_dir, "test.db")
    storage = SQLiteStorage(db)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
    mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
    yield mgr
    storage.close()


# ---- 人格 ----


def test_default_personality_6_dimensions(manager):
    assert len(manager.personality) == 6


def test_default_personality_all_50(manager):
    for key, val in manager.personality.items():
        assert val == 50, f"{key} 应该是 50，实际是 {val}"


def test_personality_keys_hexaco(manager):
    """HEXACO 单字母 key"""
    expected = {"H", "E", "X", "A", "C", "O"}
    assert set(manager.personality.keys()) == expected


# ---- remember ----


@pytest.mark.asyncio
async def test_remember_basic(manager):
    r = await manager.remember("测试记忆", layer="core")
    assert r.created


@pytest.mark.asyncio
async def test_remember_idempotent(manager):
    r1 = await manager.remember("相同内容", layer="core")
    r2 = await manager.remember("相同内容", layer="core")
    assert r1.created is True
    assert r2.created is False


@pytest.mark.asyncio
async def test_remember_different_layers(manager):
    r1 = await manager.remember("规范A", layer="core")
    r2 = await manager.remember("规范A", layer="standard")
    assert r1.created is True
    assert r2.created is True


@pytest.mark.asyncio
async def test_remember_audit_log(manager):
    await manager.remember("审计测试", layer="core")
    entries = manager.audit.query(action=AuditAction.MEMORY_WRITE)
    assert len(entries) >= 1


# ---- recall ----


@pytest.mark.asyncio
async def test_recall_after_remember(manager):
    await manager.remember("搜索测试内容", layer="core")
    results = await manager.recall("搜索测试", layer="core")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_recall_empty_query(manager):
    await manager.remember("热记忆", layer="core")
    results = await manager.recall("", layer="core")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_recall_no_results(manager):
    results = await manager.recall("不存在的关键词")
    assert results == []


# ---- build_context ----


@pytest.mark.asyncio
async def test_build_context_structure(manager):
    ctx = await manager.build_context()
    assert "personality" in ctx
    assert "hot_memories" in ctx
    assert "standards" in ctx


@pytest.mark.asyncio
async def test_build_context_personality(manager):
    ctx = await manager.build_context()
    assert len(ctx["personality"]) == 6


@pytest.mark.asyncio
async def test_build_context_includes_hot_memories(manager):
    await manager.remember("热记忆", layer="core")
    ctx = await manager.build_context()
    assert isinstance(ctx["hot_memories"], list)


# ---- 只读模式 ----


@pytest.mark.asyncio
async def test_read_only_rejects_write(tmp_dir):
    db = os.path.join(tmp_dir, "test.db")
    storage = SQLiteStorage(db)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
    mgr = MemoryManager(storage, tmp_dir, audit_logger=audit, read_only=True)
    r = await mgr.remember("只读测试")
    assert r.created is False
    assert "只读" in r.message
    storage.close()


# ---- 人格校验 ----


def test_personality_default_all_50(manager):
    """默认人格全为 50"""
    for k, v in manager.personality.items():
        assert v == 50


def test_personality_6_dimensions(manager):
    """HEXACO 6 维度"""
    assert set(manager.personality.keys()) == {"H", "E", "X", "A", "C", "O"}


# ---- 人格加载校验 ----


def test_load_personality_valid(tmp_dir):
    """合法的 personality.md 正常加载"""
    import os
    from pathlib import Path

    # 写入合法的 personality.md（Markdown 表格格式）
    content = (
        "# 人格配置\n\n"
        "| 维度 | 分值 | 说明 |\n"
        "|------|------|------|\n"
        "| H | 60 | 诚实-谦逊 |\n"
        "| E | 40 | 情绪性 |\n"
        "| X | 55 | 外向性 |\n"
        "| A | 70 | 宜人性 |\n"
        "| C | 65 | 尽责性 |\n"
        "| O | 50 | 经验开放性 |\n"
    )
    Path(tmp_dir, "personality.md").write_text(content, encoding="utf-8")
    db = os.path.join(tmp_dir, "test.db")
    storage = SQLiteStorage(db)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
    mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
    assert mgr.personality["H"] == 60
    assert mgr.personality["E"] == 40
    storage.close()


def test_load_personality_missing_file(tmp_dir):
    """personality.md 不存在 → 降级默认全50"""
    db = os.path.join(tmp_dir, "test.db")
    storage = SQLiteStorage(db)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
    mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
    assert all(v == 50 for v in mgr.personality.values())
    storage.close()


def test_load_personality_invalid_json(tmp_dir):
    """personality.md 格式错误 → 降级默认全50"""
    from pathlib import Path

    Path(tmp_dir, "personality.md").write_text("不是有效的格式 {{{", encoding="utf-8")
    db = os.path.join(tmp_dir, "test.db")
    storage = SQLiteStorage(db)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
    mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
    assert all(v == 50 for v in mgr.personality.values())
    storage.close()
