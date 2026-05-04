"""
单元测试 — 凭证池 (src/security/guard.py - CredentialPool)

覆盖：
- CredentialPool 初始化
- add() - 添加凭证
- get() - 获取凭证
- CredentialEntry 数据类
"""

import pytest

from src.security.guard import CredentialEntry, CredentialPool


@pytest.fixture
def pool():
    return CredentialPool()


class TestCredentialEntry:
    def test_defaults(self):
        entry = CredentialEntry()
        assert entry.key == ""
        assert entry.value == ""
        assert entry.provider == ""
        assert entry.use_count == 0
        assert entry.last_used is None

    def test_custom(self):
        entry = CredentialEntry(key="openai_key", value="sk-xxx", provider="openai")
        assert entry.key == "openai_key"
        assert entry.value == "sk-xxx"
        assert entry.provider == "openai"


class TestCredentialPoolInit:
    def test_empty_on_init(self):
        pool = CredentialPool()
        assert pool._credentials == {}


class TestAdd:
    def test_add_credential(self, pool):
        pool.add("openai_key", "sk-test-key", "openai")
        assert "openai_key" in pool._credentials
        assert pool._credentials["openai_key"].value == "sk-test-key"

    def test_add_without_provider(self, pool):
        pool.add("my_key", "my_value")
        assert pool._credentials["my_key"].provider == ""

    def test_add_empty_value_raises(self, pool):
        with pytest.raises(ValueError, match="不能为空"):
            pool.add("bad_key", "")

    def test_add_none_value_raises(self, pool):
        with pytest.raises(ValueError):
            pool.add("bad_key", None)

    def test_overwrite_existing(self, pool):
        pool.add("key1", "value1")
        pool.add("key1", "value2")
        assert pool._credentials["key1"].value == "value2"


class TestGet:
    def test_get_existing(self, pool):
        pool.add("openai_key", "sk-test", "openai")
        value = pool.get("openai_key")
        assert value == "sk-test"

    def test_get_nonexistent_raises(self, pool):
        with pytest.raises(KeyError):
            pool.get("nonexistent")

    def test_get_tracks_usage(self, pool):
        pool.add("key1", "val1")
        pool.get("key1")
        entry = pool._credentials["key1"]
        assert entry.use_count == 1
        assert entry.last_used is not None

    def test_get_multiple_uses(self, pool):
        pool.add("key1", "val1")
        pool.get("key1")
        pool.get("key1")
        pool.get("key1")
        assert pool._credentials["key1"].use_count == 3
