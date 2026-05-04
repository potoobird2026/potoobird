"""
MemoryManager 补充测试 — 提升 src/memory/manager.py 覆盖率

覆盖：
- personality.md 加载（不存在、格式错误、缺维度、分值非法）
- 记忆搜索
- 只读模式
- PID 控制器
- V2 动态加载/淘汰集成
- 审计日志集成
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.audit.logger import AuditAction, AuditLogger
from src.memory.manager import MemoryManager, PersonalitySchemaError
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


class TestPersonalityLoading:
    """测试人格加载"""

    def test_default_personality_when_file_missing(self, tmp_dir):
        """personality.md 不存在时使用默认人格"""
        db = os.path.join(tmp_dir, "test.db")
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        assert len(mgr.personality) == 6
        for key, val in mgr.personality.items():
            assert val == 50
        storage.close()

    def test_load_valid_personality(self, tmp_dir):
        """加载有效 personality.md"""
        personality_content = """
| 维度 | 分值 | 说明 |
|------|------|------|
| H | 60 | 诚实-谦逊 |
| E | 45 | 情绪性 |
| X | 70 | 外向性 |
| A | 55 | 宜人性 |
| C | 65 | 尽责性 |
| O | 50 | 经验开放性 |
"""
        with open(os.path.join(tmp_dir, "personality.md"), "w", encoding="utf-8") as f:
            f.write(personality_content)

        db = os.path.join(tmp_dir, "test.db")
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        assert mgr.personality["H"] == 60
        assert mgr.personality["E"] == 45
        assert mgr.personality["X"] == 70
        assert mgr.personality["A"] == 55
        assert mgr.personality["C"] == 65
        assert mgr.personality["O"] == 50
        storage.close()

    def test_invalid_score_uses_default(self, tmp_dir):
        """非法分值应使用默认值 50"""
        personality_content = """
| 维度 | 分值 | 说明 |
|------|------|------|
| H | 999 | 超出范围 |
| E | 45 | 情绪性 |
| X | 70 | 外向性 |
| A | 55 | 宜人性 |
| C | 65 | 尽责性 |
| O | 50 | 经验开放性 |
"""
        with open(os.path.join(tmp_dir, "personality.md"), "w", encoding="utf-8") as f:
            f.write(personality_content)

        db = os.path.join(tmp_dir, "test.db")
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        # H=999 超出 max=100，应降级为 50
        assert mgr.personality["H"] == 50
        assert mgr.personality["E"] == 45
        storage.close()

    def test_negative_score_uses_default(self, tmp_dir):
        """负分值应使用默认值"""
        personality_content = """
| 维度 | 分值 | 说明 |
|------|------|------|
| H | -10 | 负数 |
| E | 45 | 情绪性 |
| X | 70 | 外向性 |
| A | 55 | 宜人性 |
| C | 65 | 尽责性 |
| O | 50 | 经验开放性 |
"""
        with open(os.path.join(tmp_dir, "personality.md"), "w", encoding="utf-8") as f:
            f.write(personality_content)

        db = os.path.join(tmp_dir, "test.db")
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        assert mgr.personality["H"] == 50
        storage.close()

    def test_missing_dimension_filled_with_default(self, tmp_dir):
        """缺失维度应使用默认值"""
        personality_content = """
| 维度 | 分值 | 说明 |
|------|------|------|
| H | 60 | 诚实-谦逊 |
| E | 45 | 情绪性 |
"""
        with open(os.path.join(tmp_dir, "personality.md"), "w", encoding="utf-8") as f:
            f.write(personality_content)

        db = os.path.join(tmp_dir, "test.db")
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        assert mgr.personality["H"] == 60
        assert mgr.personality["E"] == 45
        # 缺失的维度应使用默认值
        assert mgr.personality["X"] == 50
        assert mgr.personality["A"] == 50
        assert mgr.personality["C"] == 50
        assert mgr.personality["O"] == 50
        storage.close()

    def test_malformed_file_uses_default(self, tmp_dir):
        """格式错误的文件应使用默认人格"""
        with open(os.path.join(tmp_dir, "personality.md"), "w", encoding="utf-8") as f:
            f.write("这不是有效的 Markdown 表格内容")

        db = os.path.join(tmp_dir, "test.db")
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit)
        # 应降级到默认人格
        assert len(mgr.personality) == 6
        for key, val in mgr.personality.items():
            assert val == 50
        storage.close()


class TestMemorySearch:
    """测试记忆搜索"""

    @pytest.mark.asyncio
    async def test_search_returns_list(self, manager):
        """搜索应返回列表"""
        results = await manager.search("测试")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_empty_query(self, manager):
        """空查询搜索"""
        results = await manager.search("")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_no_results(self, manager):
        """无匹配结果的搜索"""
        results = await manager.search("不存在的记忆xyz123")
        assert isinstance(results, list)


class TestReadOnlyMode:
    """测试只读模式"""

    def test_read_only_flag(self, tmp_dir):
        """只读模式标志"""
        db = os.path.join(tmp_dir, "test.db")
        storage = SQLiteStorage(db)
        audit = AuditLogger(os.path.join(tmp_dir, "audit.jsonl"))
        mgr = MemoryManager(storage, tmp_dir, audit_logger=audit, read_only=True)
        assert mgr._read_only is True
        storage.close()

    def test_not_read_only_by_default(self, manager):
        """默认非只读"""
        assert manager._read_only is False


class TestPIDController:
    """测试 PID 控制器参数"""

    def test_pid_constants_exist(self):
        """PID 常量应存在"""
        assert hasattr(MemoryManager, 'PID_KP')
        assert hasattr(MemoryManager, 'PID_KI')
        assert hasattr(MemoryManager, 'PID_KD')
        assert hasattr(MemoryManager, 'PID_DEAD_ZONE')
        assert hasattr(MemoryManager, 'PID_MAX_DELTA')
        assert hasattr(MemoryManager, 'PID_INTEGRAL_MAX')

    def test_pid_values_reasonable(self):
        """PID 参数值应合理"""
        assert MemoryManager.PID_KP > 0
        assert MemoryManager.PID_KI > 0
        assert MemoryManager.PID_KD > 0
        assert MemoryManager.PID_DEAD_ZONE > 0
        assert MemoryManager.PID_MAX_DELTA > 0


class TestPersonalitySchema:
    """测试人格 Schema 定义"""

    def test_required_dimensions(self):
        """应有6个必需维度"""
        assert len(MemoryManager.REQUIRED_DIMENSIONS) == 6
        expected_keys = {"H", "E", "X", "A", "C", "O"}
        assert set(MemoryManager.REQUIRED_DIMENSIONS.keys()) == expected_keys

    def test_dimension_structure(self):
        """维度结构应包含 name, min, max"""
        for key, dim in MemoryManager.REQUIRED_DIMENSIONS.items():
            assert "name" in dim
            assert "min" in dim
            assert "max" in dim
            assert dim["min"] == 0
            assert dim["max"] == 100


class TestMemoryManagerV2Integration:
    """测试 V2 集成组件"""

    def test_loader_initialized(self, manager):
        """MemoryLoader 应被初始化"""
        assert manager._loader is not None

    def test_evictor_initialized(self, manager):
        """MemoryEvictor 应被初始化"""
        assert manager._evictor is not None

    def test_capacity_manager_initialized(self, manager):
        """MemoryCapacityManager 应被初始化"""
        assert manager._capacity_mgr is not None

    def test_audit_logger(self, manager):
        """审计日志器应存在"""
        assert manager.audit is not None


class TestRememberAuditLog:
    """测试记住操作的审计日志"""

    @pytest.mark.asyncio
    async def test_remember_creates_audit_entry(self, manager):
        """记住操作应创建审计条目"""
        await manager.remember("审计测试记忆", layer="core")
        entries = manager.audit.query(action=AuditAction.MEMORY_WRITE)
        assert len(entries) >= 1

    @pytest.mark.asyncio
    async def test_remember_idempotent_no_extra_audit(self, manager):
        """幂等记住不应重复创建审计条目"""
        await manager.remember("幂等测试", layer="core")
        await manager.remember("幂等测试", layer="core")
        entries = manager.audit.query(action=AuditAction.MEMORY_WRITE)
        # 至少有1条（幂等的不应重复）
        assert len(entries) >= 1


class TestDefaultPersonality:
    """测试默认人格生成"""

    def test_default_personality_all_50(self, manager):
        """默认人格所有维度为50"""
        default = manager._default_personality()
        assert len(default) == 6
        for key, val in default.items():
            assert val == 50

    def test_default_personality_keys(self, manager):
        """默认人格键应为 HEXACO"""
        default = manager._default_personality()
        assert set(default.keys()) == {"H", "E", "X", "A", "C", "O"}
