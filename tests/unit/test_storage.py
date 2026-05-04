"""
单元测试 — SQLiteStorage
"""

import os
import tempfile

import pytest

from src.errors.types import ErrorCode
from src.memory.storage.base import Memory
from src.memory.storage.sqlite_storage import SQLiteStorage


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "test.db")
        s = SQLiteStorage(db)
        yield s
        s.close()


@pytest.mark.asyncio
async def test_upsert_creates_memory(storage):
    m = Memory(content="单元测试", layer="core")
    r = await storage.upsert(m)
    assert r.created
    assert r.id is not None


@pytest.mark.asyncio
async def test_upsert_returns_id(storage):
    m = Memory(content="有ID", layer="core")
    r = await storage.upsert(m)
    assert len(r.id) > 0


@pytest.mark.asyncio
async def test_get_existing(storage):
    m = Memory(content="获取测试", layer="core")
    r = await storage.upsert(m)
    got = await storage.get(r.id)
    assert got is not None
    assert got.content == "获取测试"


@pytest.mark.asyncio
async def test_get_nonexistent(storage):
    got = await storage.get("nonexistent")
    assert got is None


@pytest.mark.asyncio
async def test_find_by_content_found(storage):
    m = Memory(content="精确匹配测试", layer="core")
    await storage.upsert(m)
    found = await storage.find_by_content("精确匹配测试", layer="core")
    assert found is not None
    assert found.content == "精确匹配测试"


@pytest.mark.asyncio
async def test_find_by_content_not_found(storage):
    found = await storage.find_by_content("不存在", layer="core")
    assert found is None


@pytest.mark.asyncio
async def test_find_by_content_wrong_layer(storage):
    m = Memory(content="层测试", layer="core")
    await storage.upsert(m)
    found = await storage.find_by_content("层测试", layer="standard")
    assert found is None


@pytest.mark.asyncio
async def test_search_english(storage):
    m = Memory(content="Python programming guide", layer="core")
    await storage.upsert(m)
    results = await storage.search("Python", layer="core")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_chinese(storage):
    m = Memory(content="中文搜索测试内容", layer="core")
    await storage.upsert(m)
    results = await storage.search("中文", layer="core")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_empty_query(storage):
    m = Memory(content="空查询测试", layer="core")
    await storage.upsert(m)
    results = await storage.search("", layer="core")
    assert len(results) >= 1  # 返回最近更新


@pytest.mark.asyncio
async def test_search_no_results(storage):
    results = await storage.search("不存在的词", layer="core")
    assert results == []


@pytest.mark.asyncio
async def test_count_all(storage):
    for i in range(5):
        await storage.upsert(Memory(content=f"计数{i}", layer="core"))
    assert await storage.count() == 5


@pytest.mark.asyncio
async def test_count_by_layer(storage):
    await storage.upsert(Memory(content="core记忆", layer="core"))
    await storage.upsert(Memory(content="standard记忆", layer="standard"))
    assert await storage.count(layer="core") == 1
    assert await storage.count(layer="standard") == 1


@pytest.mark.asyncio
async def test_count_empty(storage):
    assert await storage.count(layer="core") == 0


@pytest.mark.asyncio
async def test_delete_existing(storage):
    m = Memory(content="待删除", layer="core")
    r = await storage.upsert(m)
    result = await storage.delete(r.id)
    assert result.is_ok
    assert await storage.get(r.id) is None


@pytest.mark.asyncio
async def test_delete_not_found(storage):
    result = await storage.delete("nonexistent")
    assert result.is_err
    assert result.error_code == ErrorCode.NOT_FOUND


@pytest.mark.asyncio
async def test_update_access_count(storage):
    m = Memory(content="访问计数测试", layer="core")
    r = await storage.upsert(m)
    await storage.update_access_count(r.id, delta=5)
    got = await storage.get(r.id)
    assert got.access_count == 5


@pytest.mark.asyncio
async def test_decay_all_access_counts(storage):
    for i in range(3):
        m = Memory(content=f"衰减{i}", layer="core", access_count=100)
        await storage.upsert(m)
    await storage.decay_all_access_counts(0.5)
    rows = storage.conn.execute("SELECT access_count FROM memories").fetchall()
    for row in rows:
        assert row[0] == 50


@pytest.mark.asyncio
async def test_batch_upsert(storage):
    memories = [Memory(content=f"批量{i}", layer="core") for i in range(10)]
    result = await storage.batch_upsert(memories)
    assert result.success_count == 10
    assert result.failed_count == 0


@pytest.mark.asyncio
async def test_batch_get(storage):
    ids = []
    for i in range(5):
        m = Memory(content=f"批量获取{i}", layer="core")
        r = await storage.upsert(m)
        ids.append(r.id)
    results = await storage.batch_get(ids)
    assert len(results) == 5


@pytest.mark.asyncio
async def test_get_by_zone(storage):
    m = Memory(content="热区测试", layer="core")
    await storage.upsert(m)
    results = await storage.get_by_zone("warm")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_backup(storage):
    await storage.upsert(Memory(content="备份测试", layer="core"))
    with tempfile.TemporaryDirectory() as d:
        backup_path = storage.backup(d)
        assert os.path.exists(backup_path)


@pytest.mark.asyncio
async def test_update_existing(storage):
    m = Memory(content="原始内容", layer="core")
    r = await storage.upsert(m)
    m.content = "更新内容"
    m.id = r.id
    r2 = await storage.upsert(m)
    assert r2.created  # INSERT OR REPLACE 总是返回 True
    got = await storage.get(r.id)
    assert got.content == "更新内容"


@pytest.mark.asyncio
async def test_layer_separation(storage):
    """不同 layer 的内容互不影响"""
    await storage.upsert(Memory(content="core内容", layer="core"))
    await storage.upsert(Memory(content="standard内容", layer="standard"))
    assert await storage.count(layer="core") == 1
    assert await storage.count(layer="standard") == 1
    assert await storage.count() == 2
