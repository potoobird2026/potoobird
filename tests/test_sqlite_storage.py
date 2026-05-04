"""
SQLite 存储测试
"""

import tempfile
from pathlib import Path

import pytest

from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as d:
        db_path = str(Path(d) / "test.db")
        storage = SQLiteStorage(db_path)
        yield storage
        storage.close()


@pytest.mark.asyncio
async def test_upsert_and_get(tmp_db):
    mem = Memory(content="测试记忆", layer="core", category="test")
    result = await tmp_db.upsert(mem)
    assert result.created is True
    assert result.id != ""

    fetched = await tmp_db.get(result.id)
    assert fetched is not None
    assert fetched.content == "测试记忆"
    assert fetched.layer == "core"


@pytest.mark.asyncio
async def test_find_by_content(tmp_db):
    mem = Memory(content="精确匹配测试", layer="core")
    await tmp_db.upsert(mem)

    found = await tmp_db.find_by_content("精确匹配测试", layer="core")
    assert found is not None
    assert found.content == "精确匹配测试"

    not_found = await tmp_db.find_by_content("不存在的内容")
    assert not_found is None


@pytest.mark.asyncio
async def test_search_fts5(tmp_db):
    await tmp_db.upsert(Memory(content="Python 编程经验", layer="core"))
    await tmp_db.upsert(Memory(content="JavaScript 前端开发", layer="core"))

    results = await tmp_db.search("Python", layer="core")
    assert len(results) >= 1
    assert any("Python" in r.content for r in results)


@pytest.mark.asyncio
async def test_delete(tmp_db):
    mem = Memory(content="待删除", layer="core")
    result = await tmp_db.upsert(mem)

    deleted = await tmp_db.delete(result.id)
    assert deleted.ok is True

    fetched = await tmp_db.get(result.id)
    assert fetched is None


@pytest.mark.asyncio
async def test_count(tmp_db):
    assert await tmp_db.count() == 0
    await tmp_db.upsert(Memory(content="记忆1", layer="core"))
    await tmp_db.upsert(Memory(content="记忆2", layer="core"))
    await tmp_db.upsert(Memory(content="标准1", layer="standard"))
    assert await tmp_db.count() == 3
    assert await tmp_db.count(layer="core") == 2


@pytest.mark.asyncio
async def test_update_access_count(tmp_db):
    mem = Memory(content="访问计数测试", layer="core")
    result = await tmp_db.upsert(mem)

    await tmp_db.update_access_count(result.id, delta=5)
    fetched = await tmp_db.get(result.id)
    assert fetched.access_count == 5


@pytest.mark.asyncio
async def test_batch_upsert(tmp_db):
    memories = [Memory(content=f"批量记忆{i}", layer="core") for i in range(5)]
    result = await tmp_db.batch_upsert(memories)
    assert result.success_count == 5
    assert result.failed_count == 0


@pytest.mark.asyncio
async def test_backup(tmp_db):
    mem = Memory(content="备份测试", layer="core")
    await tmp_db.upsert(mem)

    with tempfile.TemporaryDirectory() as backup_dir:
        backup_path = tmp_db.backup(backup_dir, keep=3)
        assert Path(backup_path).exists()
