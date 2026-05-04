"""
记忆存储抽象接口

设计原则：
- 接口与实现分离（V1 SQLite，V2 可换 Redis）
- 所有方法均为 async（为 V2 Redis 做准备）
- 幂等性由存储层保证（find_by_content + upsert）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.errors.types import OperationResult


@dataclass
class Memory:
    """记忆实体"""

    id: str = ""
    content: str = ""
    layer: str = "core"  # personality / core / standard
    category: str = "general"
    source: str = "conversation"  # conversation / user_edit / system
    evidence: str = ""
    tags: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    access_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat() + "Z"
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def touch(self):
        """更新时间戳"""
        self.updated_at = datetime.now(timezone.utc).isoformat() + "Z"


@dataclass
class MemoryWriteResult:
    """写入结果"""

    id: str = ""
    created: bool = True  # True=新建, False=更新（幂等命中）
    message: str = ""
    conflicts: list[str] = field(default_factory=list)


@dataclass
class BatchWriteResult:
    """批量写入结果"""

    success_count: int = 0
    failed_count: int = 0
    failed_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ConflictResult:
    """冲突检测结果"""

    has_conflicts: bool = False
    conflicts: list = field(default_factory=list)  # list[Memory]
    merged_content: str = ""  # V2：自动整合后的内容


@dataclass
class Snapshot:
    """任务快照"""

    id: str = ""
    task_id: str = ""
    state: dict = field(default_factory=dict)
    created_at: str = ""


class MemoryStorage(ABC):
    """
    记忆存储抽象接口

    MVP：SQLite 实现
    V2：Redis 实现（热区缓存）+ SQLite 实现（持久化）
    """

    @abstractmethod
    async def get(self, memory_id: str) -> Optional[Memory]: ...

    @abstractmethod
    async def find_by_content(self, content: str, layer: str = None) -> Optional[Memory]:
        """精确匹配内容（用于幂等性检查）"""
        ...

    @abstractmethod
    async def search(self, query: str, layer: str = None, limit: int = 10) -> list[Memory]: ...

    @abstractmethod
    async def upsert(self, memory: Memory) -> MemoryWriteResult: ...

    @abstractmethod
    async def delete(self, memory_id: str) -> OperationResult: ...

    @abstractmethod
    async def count(self, layer: str = None) -> int: ...

    # ---- 批量操作 ----

    @abstractmethod
    async def batch_upsert(self, memories: list[Memory]) -> BatchWriteResult: ...

    @abstractmethod
    async def batch_get(self, memory_ids: list[str]) -> list[Memory]: ...

    @abstractmethod
    async def batch_update_access_counts(self, updates: dict[str, int]): ...

    @abstractmethod
    async def get_by_zone(self, zone: str, limit: int = 100) -> list[Memory]: ...

    @abstractmethod
    async def update_access_count(self, memory_id: str, delta: int = 1): ...

    @abstractmethod
    async def decay_all_access_counts(self, factor: float = 0.9): ...

    @abstractmethod
    async def get_old_snapshots(self, days: int = 7) -> list[Snapshot]: ...

    @abstractmethod
    async def delete_snapshots(self, snapshot_ids: list[str]): ...

    @abstractmethod
    async def vacuum(self): ...

    @abstractmethod
    def backup(self, backup_path: str) -> str:
        """返回备份文件路径"""
        ...

    @abstractmethod
    def close(self): ...

    # ---- 事务支持 ----

    @abstractmethod
    async def begin_transaction(self): ...

    @abstractmethod
    async def commit(self): ...

    @abstractmethod
    async def rollback(self): ...
