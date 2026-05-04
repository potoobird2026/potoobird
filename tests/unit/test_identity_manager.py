"""
单元测试 — 统一身份管理器 (src/session/identity_manager.py)

覆盖：
- IdentityManager 初始化
- resolve() - 解析渠道用户ID
- bind() - 主动绑定
- get_channels() - 获取渠道列表
- count - 计数属性
- 持久化加载/保存
"""

import json
import os
from pathlib import Path

import pytest
from src.session.identity_manager import IdentityManager


@pytest.fixture
def tmp_storage(tmp_path):
    return str(tmp_path / "identities.json")


@pytest.fixture
def manager(tmp_storage):
    return IdentityManager(storage_path=tmp_storage)


class TestInit:
    def test_default_storage_path(self):
        im = IdentityManager()
        assert im._storage_path == "./data/identities.json"

    def test_custom_storage_path(self, tmp_storage):
        im = IdentityManager(storage_path=tmp_storage)
        assert im._storage_path == tmp_storage

    def test_empty_on_fresh_start(self, manager):
        assert manager._identity_map == {}
        assert manager._reverse_map == {}

    def test_loads_existing_data(self, tmp_storage):
        data = {"identity_map": {"wechat:user1": "abc123", "telegram:user2": "abc123"}}
        Path(tmp_storage).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_storage).write_text(json.dumps(data))

        im = IdentityManager(storage_path=tmp_storage)
        assert "wechat:user1" in im._identity_map
        assert im._identity_map["wechat:user1"] == "abc123"
        assert "abc123" in im._reverse_map

    def test_load_corrupt_file(self, tmp_storage):
        Path(tmp_storage).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_storage).write_text("not json{{{")
        im = IdentityManager(storage_path=tmp_storage)
        assert im._identity_map == {}
        assert im._reverse_map == {}

    def test_load_valid_json_wrong_format(self, tmp_storage):
        Path(tmp_storage).parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_storage).write_text('{"foo": "bar"}')
        im = IdentityManager(storage_path=tmp_storage)
        assert im._identity_map == {}


class TestResolve:
    @pytest.mark.asyncio
    async def test_new_user_creates_universal_id(self, manager):
        uid = await manager.resolve("wechat", "user123")
        assert uid is not None
        assert len(uid) == 12

    @pytest.mark.asyncio
    async def test_existing_user_returns_same_id(self, manager):
        uid1 = await manager.resolve("wechat", "user123")
        uid2 = await manager.resolve("wechat", "user123")
        assert uid1 == uid2

    @pytest.mark.asyncio
    async def test_different_user_ids_get_different_uids(self, manager):
        uid1 = await manager.resolve("wechat", "alice")
        uid2 = await manager.resolve("telegram", "bob")
        assert uid1 != uid2

    @pytest.mark.asyncio
    async def test_same_user_id_auto_matches(self, manager):
        uid1 = await manager.resolve("wechat", "shared_user")
        uid2 = await manager.resolve("telegram", "shared_user")
        assert uid1 == uid2

    @pytest.mark.asyncio
    async def test_persists_after_resolve(self, manager, tmp_storage):
        await manager.resolve("wechat", "user123")
        assert os.path.exists(tmp_storage)
        data = json.loads(Path(tmp_storage).read_text())
        assert "wechat:user123" in data["identity_map"]

    @pytest.mark.asyncio
    async def test_reverse_map_updated(self, manager):
        uid = await manager.resolve("wechat", "user1")
        assert uid in manager._reverse_map
        assert "wechat:user1" in manager._reverse_map[uid]


class TestBind:
    @pytest.mark.asyncio
    async def test_bind_one_resolved_one_new(self, manager):
        uid1 = await manager.resolve("wechat", "alice")
        uid = await manager.bind("wechat", "alice", "telegram", "bob")
        assert uid == uid1
        assert manager._identity_map["wechat:alice"] == uid1
        assert manager._identity_map["telegram:bob"] == uid1

    @pytest.mark.asyncio
    async def test_bind_both_new(self, manager):
        uid = await manager.bind("wechat", "new_user", "telegram", "new_user")
        assert uid is not None
        assert manager._identity_map["wechat:new_user"] == uid
        assert manager._identity_map["telegram:new_user"] == uid

    @pytest.mark.asyncio
    async def test_bind_same_user_id(self, manager):
        uid1 = await manager.resolve("wechat", "same_user")
        uid = await manager.bind("wechat", "same_user", "telegram", "same_user")
        assert uid == uid1

    @pytest.mark.asyncio
    async def test_bind_creates_reverse_map(self, manager):
        await manager.bind("wechat", "user1", "telegram", "user2")
        uid = manager._identity_map["wechat:user1"]
        assert uid in manager._reverse_map
        assert "wechat:user1" in manager._reverse_map[uid]
        assert "telegram:user2" in manager._reverse_map[uid]

    @pytest.mark.asyncio
    async def test_bind_conflict_raises(self, manager):
        await manager.resolve("wechat", "user_a")
        await manager.resolve("telegram", "user_b")
        with pytest.raises(ValueError, match="身份冲突"):
            await manager.bind("wechat", "user_a", "telegram", "user_b")

    @pytest.mark.asyncio
    async def test_bind_persists(self, manager, tmp_storage):
        await manager.bind("wechat", "persist_user", "telegram", "persist_user")
        data = json.loads(Path(tmp_storage).read_text())
        assert "wechat:persist_user" in data["identity_map"]
        assert "telegram:persist_user" in data["identity_map"]


class TestGetChannels:
    def test_empty_for_unknown(self, manager):
        assert manager.get_channels("nonexistent_uid") == []

    @pytest.mark.asyncio
    async def test_returns_channels(self, manager):
        await manager.bind("wechat", "user1", "telegram", "user2")
        uid = manager._identity_map["wechat:user1"]
        channels = manager.get_channels(uid)
        assert "wechat:user1" in channels
        assert "telegram:user2" in channels

    @pytest.mark.asyncio
    async def test_single_channel(self, manager):
        await manager.resolve("wechat", "solo")
        uid = manager._identity_map["wechat:solo"]
        channels = manager.get_channels(uid)
        assert "wechat:solo" in channels


class TestCount:
    def test_count_empty(self, manager):
        assert manager.count == 0

    @pytest.mark.asyncio
    async def test_count_after_resolve(self, manager):
        await manager.resolve("wechat", "user1")
        assert manager.count == 1

    @pytest.mark.asyncio
    async def test_count_after_bind(self, manager):
        await manager.resolve("wechat", "user1")
        await manager.resolve("telegram", "user2")
        assert manager.count == 2

    @pytest.mark.asyncio
    async def test_count_same_user(self, manager):
        await manager.resolve("wechat", "same")
        await manager.resolve("telegram", "same")
        assert manager.count == 1


class TestSave:
    def test_save_creates_file(self, manager, tmp_storage):
        manager._identity_map["wechat:test"] = "abc123"
        manager._reverse_map["abc123"] = {"wechat:test"}
        manager._save()
        assert os.path.exists(tmp_storage)
        data = json.loads(Path(tmp_storage).read_text())
        assert data["identity_map"]["wechat:test"] == "abc123"

    def test_save_creates_parent_dirs(self, tmp_path):
        storage = str(tmp_path / "sub" / "dir" / "identities.json")
        im = IdentityManager(storage_path=storage)
        im._identity_map["test"] = "val"
        im._save()
        assert os.path.exists(storage)
