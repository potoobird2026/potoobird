"""
集成测试 — 记忆系统全流程

验证模块间协作：SQLiteStorage + MemoryManager + AuditLogger
"""

import os
import tempfile

import pytest

from src.audit.logger import AuditAction, AuditLogger
from src.errors.types import ErrorCode
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


@pytest.mark.asyncio
async def test_remember_and_recall(manager):
    """写入 → 搜索 → 验证"""
    await manager.remember("Python 编程经验", layer="core")
    results = await manager.recall("Python", layer="core")
    assert len(results) >= 1
    assert results[0].content == "Python 编程经验"


@pytest.mark.asyncio
async def test_idempotent_remember(manager):
    """相同内容写入两次 → 不重复创建"""
    r1 = await manager.remember("相同内容", layer="core")
    r2 = await manager.remember("相同内容", layer="core")
    assert r1.created is True
    assert r2.created is False


@pytest.mark.asyncio
async def test_different_layers_same_content(manager):
    """不同 layer 允许相同内容"""
    r1 = await manager.remember("规范A", layer="core")
    r2 = await manager.remember("规范A", layer="standard")
    assert r1.created is True
    assert r2.created is True


@pytest.mark.asyncio
async def test_delete_memory(manager):
    """写入 → 删除 → 验证不存在"""
    r = await manager.remember("待删除", layer="core")
    assert r.created

    result = await manager.storage.delete(r.id)
    assert result.is_ok

    found = await manager.storage.find_by_content("待删除", layer="core")
    assert found is None


@pytest.mark.asyncio
async def test_delete_not_found(manager):
    """删除不存在的记忆"""
    result = await manager.storage.delete("nonexistent-id")
    assert result.is_err
    assert result.error_code == ErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_audit_log_written(manager):
    """写入记忆 → 审计日志有记录"""
    await manager.remember("审计测试", layer="core")
    entries = manager.audit.query(action=AuditAction.MEMORY_WRITE)
    assert len(entries) >= 1


@pytest.mark.asyncio
async def test_build_context(manager):
    """构建上下文包含人格+热记忆+标准"""
    await manager.remember("热记忆", layer="core")
    ctx = await manager.build_context()
    assert "personality" in ctx
    assert len(ctx["personality"]) == 6  # HEXACO


@pytest.mark.asyncio
async def test_read_only_mode(tmp_dir):
    """只读模式拒绝写入"""
    db = os.path.join(tmp_dir, "test.db")
    storage = SQLiteStorage(db)
    audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
    mgr = MemoryManager(storage, tmp_dir, audit_logger=audit, read_only=True)

    result = await mgr.remember("只读测试")
    assert result.created is False
    assert "只读" in result.message

    storage.close()


@pytest.mark.asyncio
async def test_backup_and_count(manager):
    """写入多条 → 备份 → 验证数量"""
    for i in range(5):
        await manager.remember(f"记忆{i}", layer="core")
    assert await manager.storage.count(layer="core") == 5

    backup_path = manager.storage.backup(os.path.join(str(manager.data_dir), "backups"))
    assert os.path.exists(backup_path)
