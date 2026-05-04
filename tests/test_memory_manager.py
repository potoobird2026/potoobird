"""
记忆管理器测试
"""

import tempfile
from pathlib import Path

import pytest

from src.audit.logger import AuditLogger
from src.memory.manager import MemoryManager
from src.memory.storage.base import Memory, MemoryStorage, MemoryWriteResult


class InMemoryStorage(MemoryStorage):
    """内存存储 — 测试用"""

    def __init__(self):
        self._data: dict[str, Memory] = {}

    async def get(self, memory_id):
        return self._data.get(memory_id)

    async def find_by_content(self, content, layer=None):
        for mem in self._data.values():
            if mem.content == content:
                if layer is None or mem.layer == layer:
                    return mem
        return None

    async def search(self, query, layer=None, limit=10):
        results = []
        for mem in self._data.values():
            if layer and mem.layer != layer:
                continue
            if query and query not in mem.content:
                continue
            results.append(mem)
        return results[:limit]

    async def upsert(self, memory):
        if not memory.id:
            import uuid

            memory.id = str(uuid.uuid4())
        self._data[memory.id] = memory
        return MemoryWriteResult(id=memory.id, created=True)

    async def delete(self, memory_id):
        existed = memory_id in self._data
        self._data.pop(memory_id, None)
        return existed

    async def count(self, layer=None):
        if layer:
            return sum(1 for m in self._data.values() if m.layer == layer)
        return len(self._data)

    async def batch_upsert(self, memories):
        result = MemoryWriteResult(id="", created=False)
        for mem in memories:
            await self.upsert(mem)
            result.success_count += 1
        return result

    async def batch_get(self, memory_ids):
        return [self._data[mid] for mid in memory_ids if mid in self._data]

    async def batch_update_access_counts(self, updates):
        pass

    async def get_by_zone(self, zone, limit=100):
        return list(self._data.values())[:limit]

    async def update_access_count(self, memory_id, delta=1):
        pass

    async def decay_all_access_counts(self, factor=0.9):
        for mem in self._data.values():
            mem.access_count = int(mem.access_count * factor)

    async def get_old_snapshots(self, days=7):
        return []

    async def delete_snapshots(self, snapshot_ids):
        pass

    async def vacuum(self):
        pass

    def backup(self, keep=3):
        return "test_backup.db"

    def close(self):
        pass

    # ---- 事务支持（内存存储无需真实事务） ----

    async def begin_transaction(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def manager(tmp_dir):
    storage = InMemoryStorage()
    audit = AuditLogger(str(Path(tmp_dir) / "audit.jsonl"))
    return MemoryManager(storage, tmp_dir, audit_logger=audit)


@pytest.mark.asyncio
async def test_remember_creates_memory(manager):
    result = await manager.remember("测试记忆", layer="core")
    assert result.created is True
    assert result.id != ""


@pytest.mark.asyncio
async def test_remember_idempotent(manager):
    result1 = await manager.remember("相同内容", layer="core")
    result2 = await manager.remember("相同内容", layer="core")
    assert result1.created is True
    assert result2.created is False  # 幂等：不重复创建


@pytest.mark.asyncio
async def test_remember_different_layers(manager):
    result1 = await manager.remember("相同内容", layer="core")
    result2 = await manager.remember("相同内容", layer="standard")
    assert result1.created is True
    assert result2.created is True  # 不同 layer，允许


@pytest.mark.asyncio
async def test_recall(manager):
    await manager.remember("关于 Python 的记忆", layer="core")
    results = await manager.recall("Python", layer="core")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_read_only_rejects_write(tmp_dir):
    storage = InMemoryStorage()
    audit = AuditLogger(str(Path(tmp_dir) / "audit.jsonl"))
    mgr = MemoryManager(storage, tmp_dir, audit_logger=audit, read_only=True)
    result = await mgr.remember("测试", layer="core")
    assert result.created is False
    assert "只读" in result.message


@pytest.mark.asyncio
async def test_build_context(manager):
    await manager.remember("测试记忆", layer="core")
    context = await manager.build_context()
    assert "personality" in context
    assert "hot_memories" in context
    assert "standards" in context
    assert len(context["personality"]) == 6  # HEXACO 6 维度


class TestPersonalityLoading:
    def test_default_personality(self, tmp_dir):
        storage = InMemoryStorage()
        audit = AuditLogger(str(Path(tmp_dir) / "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        p = mgr.personality
        assert len(p) == 6
        assert all(v == 50 for v in p.values())

    def test_valid_personality(self, tmp_dir):
        # 写入合法的 personality.md
        md_content = """# 人格配置

| 维度 | 分值 | 说明 |
|------|------|------|
| H | 70 | 诚实-谦逊 |
| E | 40 | 情绪性 |
| X | 60 | 外向性 |
| A | 55 | 宜人性 |
| C | 80 | 尽责性 |
| O | 65 | 经验开放性 |
"""
        (Path(tmp_dir) / "personality.md").write_text(md_content, encoding="utf-8")
        storage = InMemoryStorage()
        audit = AuditLogger(str(Path(tmp_dir) / "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        assert mgr.personality["H"] == 70
        assert mgr.personality["C"] == 80

    def test_invalid_score_falls_back(self, tmp_dir):
        md_content = """# 人格配置

| 维度 | 分值 | 说明 |
|------|------|------|
| H | 150 | 超出范围 |
| E | 40 | 情绪性 |
| X | 60 | 外向性 |
| A | 55 | 宜人性 |
| C | 80 | 尽责性 |
| O | 65 | 经验开放性 |
"""
        (Path(tmp_dir) / "personality.md").write_text(md_content, encoding="utf-8")
        storage = InMemoryStorage()
        audit = AuditLogger(str(Path(tmp_dir) / "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        assert mgr.personality["H"] == 50  # 降级为默认值
        assert mgr.personality["E"] == 40  # 正常加载
