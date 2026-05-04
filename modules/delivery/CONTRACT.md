# 交付层 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## ResultVerifier 类

### 构造函数

```python
class ResultVerifier:
    def __init__(self)
```

### 核心方法

```python
async def verify(
    self,
    execution_result: ExecutionResult,  # 执行结果
    deliverable_plan: dict = None,       # 交付物计划
) -> VerificationReport
"""
三级验证：L1静态 → L2动态 → L3人工
返回 VerificationReport
"""
```

---

## 数据模型

### VerificationReport

```python
@dataclass
class VerificationReport:
    task_id: str = ""
    intent_id: str = ""
    overall_status: VerificationStatus = VerificationStatus.SKIPPED
    items: list[VerificationItem] = field(default_factory=list)
    summary: str = ""
    evidence_chain: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def pass_rate(self) -> float
    """通过率 = PASSED / (PASSED + FAILED)"""
```

### VerificationItem

```python
@dataclass
class VerificationItem:
    criterion: str = ""                 # 验证标准
    level: VerificationLevel = VerificationLevel.L1_STATIC
    status: VerificationStatus = VerificationStatus.SKIPPED
    evidence: str = ""                  # 证据
    error: str = ""
    duration: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
```

### VerificationLevel

```python
class VerificationLevel(Enum):
    L1_STATIC = 1       # 静态检查
    L2_DYNAMIC = 2      # 动态测试
    L3_MANUAL = 3       # 人工确认
```

### VerificationStatus

```python
class VerificationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
```

---

## ReportGenerator 类

### 构造函数

```python
class ReportGenerator:
    def __init__(self)
```

### 核心方法

```python
def generate(
    self,
    verification_report: VerificationReport,
    execution_result: ExecutionResult = None,
    compression_record: dict = None,
    lessons: list = None,
) -> DeliveryReport
"""
生成分层交付报告
金字塔原理：结论 → 摘要 → 详情 → 建议 → 风险
"""
```

---

## 数据模型

### DeliveryReport

```python
@dataclass
class DeliveryReport:
    task_id: str = ""
    conclusion: str = ""                # 一句话结论
    summary: str = ""                   # 摘要
    details: list = field(default_factory=list)     # 验证项详情
    suggestions: list = field(default_factory=list) # 改进建议
    risks: list = field(default_factory=list)       # 剩余风险
    evidence_chain: list = field(default_factory=list)
    deviation_history: list = field(default_factory=list)
    compression_record: dict = field(default_factory=dict)
    compression_lessons: list = field(default_factory=list)
    user_summary: dict = field(default_factory=dict)  # 用户层
    tech_detail: dict = field(default_factory=dict)   # 技术层
    active_layer: str = "summary"
    created_at: datetime = field(default_factory=datetime.now)
```

---

## ConfirmationManager 类

```python
class ConfirmationManager:
    async def wait_confirmation(
        self,
        task_id: str,
        timeout: float = 300.0,
    ) -> bool
    """等待用户确认，返回是否确认"""

    async def confirm(self, task_id: str, approved: bool) -> None
    """用户确认/拒绝"""
```
