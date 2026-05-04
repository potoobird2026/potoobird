"""
记忆管理器 — 冲突检测测试

覆盖：
- _detect_conflicts 各种场景
- _same_subject 辅助方法
- remember 中的冲突检测集成
"""

import tempfile
from pathlib import Path

import pytest

from src.memory.manager import MemoryManager
from src.memory.storage.sqlite_storage import SQLiteStorage


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def manager(temp_dir):
    """创建真实的 MemoryManager（SQLite 在临时目录）"""
    db_path = str(Path(temp_dir) / "test.db")
    storage = SQLiteStorage(db_path)
    mgr = MemoryManager(storage, temp_dir)
    yield mgr
    # Windows: 必须显式关闭 SQLite 连接，否则文件被占用
    try:
        storage.close()
    except Exception:
        pass


class TestDetectConflicts:
    """测试冲突检测"""

    @pytest.mark.asyncio
    async def test_no_conflicts_empty_storage(self, manager):
        """空存储无冲突"""
        result = await manager._detect_conflicts("新记忆内容", "core")
        assert result.has_conflicts is False
        assert len(result.conflicts) == 0

    @pytest.mark.asyncio
    async def test_conflict_direct_contradiction(self, manager):
        """直接矛盾检测"""
        # 先写入一条记忆
        await manager.remember("我喜欢 Python", "core", "preference")
        # 写入相反的记忆
        result = await manager._detect_conflicts("我不喜欢 Python", "core")
        assert result.has_conflicts is True
        assert len(result.conflicts) >= 1

    @pytest.mark.asyncio
    async def test_no_conflict_different_subject(self, manager):
        """不同主体不冲突"""
        await manager.remember("我喜欢 Java", "core", "preference")
        result = await manager._detect_conflicts("我喜欢 Python", "core")
        # 不同主体（Java vs Python），不冲突
        assert result.has_conflicts is False

    @pytest.mark.asyncio
    async def test_conflict_same_subject_opposite(self, manager):
        """相同主体 + 相反内容 → 冲突"""
        await manager.remember("今天天气很好", "core", "observation")
        result = await manager._detect_conflicts("今天天气很差", "core")
        # 主体相同（今天天气），内容相反
        assert result.has_conflicts is True


class TestSameSubject:
    """测试 _same_subject"""

    def test_same_prefix(self):
        """相同前缀"""
        assert MemoryManager._same_subject("今天天气很好", "今天天气很差") is True

    def test_different_subject(self):
        """不同主体"""
        assert MemoryManager._same_subject("今天天气很好", "明天会下雨") is False

    def test_empty_strings(self):
        """空字符串"""
        assert MemoryManager._same_subject("", "") is False

    def test_one_char_overlap(self):
        """只有一个字符重叠"""
        assert MemoryManager._same_subject("abc", "def") is False


class TestRememberWithConflicts:
    """测试 remember 中的冲突检测集成"""

    @pytest.mark.asyncio
    async def test_remember_triggers_conflict_detection(self, manager):
        """remember 会触发冲突检测"""
        # 先写入一条
        result1 = await manager.remember("我喜欢编程", "core")
        assert result1.created is True

        # 写入矛盾的
        result2 = await manager.remember("我不喜欢编程", "core")
        # 应该能写入（冲突检测不阻止写入）
        assert result2.created is True

    @pytest.mark.asyncio
    async def test_remember_idempotent_with_conflicts(self, manager):
        """幂等性在冲突检测后仍然有效"""
        await manager.remember("测试内容", "core")
        result2 = await manager.remember("测试内容", "core")
        assert result2.created is False  # 幂等命中
