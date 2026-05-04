# 执行层 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## BSupervisor 类

### 构造函数

```python
class BSupervisor:
    def __init__(
        self,
        goal_anchor: GoalAnchor = None,
        snapshot_manager: SnapshotManager = None,
        tool_registry: ToolRegistry = None,
    )
```

### 核心方法

```python
async def execute(
    self,
    intent: Intent,     # 解析后的意图
    plan: dict,         # 执行计划
) -> ExecutionResult
"""
执行监督：分解步骤 → 逐步执行 → 偏离检测 → 纠偏
"""
```

---

## GoalAnchor 类

### 构造函数

```python
class GoalAnchor:
    def __init__(self, base_threshold: float = None)
    # base_threshold: None 表示由 LLM 动态评估
```

### 核心方法

```python
def get_dynamic_threshold(self, progress: float) -> float
"""动态阈值 = base + 0.4 × progress²"""

def check(
    self,
    goal: str,          # 目标描述
    current: str,       # 当前状态
    progress: float = 0.0,  # 执行进度 0.0~1.0
) -> AnchorResult
"""检查偏离度，返回纠偏建议"""
```

---

## 数据模型

### ExecutionResult

```python
@dataclass
class ExecutionResult:
    task_id: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    steps_completed: int = 0
    steps_total: int = 0
    output: str = ""            # 执行产出（关键交付物）
    error: str = ""
    snapshots: list = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
```

### ExecutionStatus

```python
class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
```

### AnchorResult

```python
@dataclass
class AnchorResult:
    similarity: float = 0.0
    deviation: float = 0.0
    deviation_vector: dict = field(default_factory=dict)
    dynamic_threshold: float = 0.5
    is_on_track: bool = True
    action: str = "continue"    # continue / correct / ask_user / stop
    suggestion: str = ""
    details: dict = field(default_factory=dict)
```

### TaskStep

```python
@dataclass
class TaskStep:
    index: int = 0
    description: str = ""
    tool_name: str = ""
    tool_params: dict = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: str = ""
    error: str = ""
    snapshot_id: str = ""
```

---

## SnapshotManager 类

```python
class SnapshotManager:
    async def create_snapshot(self, state: dict) -> str
    """创建快照，返回 snapshot_id"""

    async def restore_snapshot(self, snapshot_id: str) -> dict
    """恢复到指定快照"""

    async def list_snapshots(self, task_id: str) -> list
    """列出任务的所有快照"""
```

---

## ToolRegistry 类

```python
class ToolRegistry:
    def register(self, name: str, func: Callable, description: str = "") -> None
    def get(self, name: str) -> Optional[Callable]
    def list_tools(self) -> list[dict]
    async def call(self, name: str, params: dict) -> dict
    """安全调用工具（含错误处理）"""
```
