# 安全模块 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## SecurityGuard 类

```python
class SecurityGuard:
    def check_input(self, user_input: str) -> SecurityCheckResult
    """检查输入是否包含注入攻击"""

    def check_path(self, path: str) -> SecurityCheckResult
    """检查路径是否包含遍历攻击"""

    def check_output(self, output: str) -> SecurityCheckResult
    """检查输出是否包含敏感信息泄露（自动脱敏）"""
```

### SecurityCheckResult

```python
@dataclass
class SecurityCheckResult:
    is_safe: bool = True
    threat_type: str = ""       # prompt_injection / path_traversal / sensitive_leak
    description: str = ""
    original_input: str = ""
    sanitized_input: str = ""   # 脱敏后的输入/输出
```

---

## ApprovalModule 类

```python
class ApprovalModule:
    def evaluate_risk(self, action: str, params: dict) -> float
    """评估操作风险评分（0.0~1.0），由 LLM 动态评估"""

    def requires_approval(self, action: str, risk_score: float) -> bool
    """判断是否需要审批"""

    async def request_approval(
        self,
        action: str,
        params: dict,
        timeout: float = 3600.0,
    ) -> ApprovalRequest
    """发起审批请求"""

    async def resolve(self, request_id: str, approved: bool, approver: str = "") -> ApprovalRequest
    """审批通过/拒绝"""

    async def check_timeout(self, request: ApprovalRequest) -> bool
    """检查审批是否超时"""
```

### ApprovalRequest

```python
@dataclass
class ApprovalRequest:
    id: str                         # 自动生成的短ID
    action: str                     # 操作名称
    params: dict                    # 操作参数
    risk_score: float               # 风险评分 0.0~1.0
    urgency_score: float = 0.5      # 紧急程度 0.0~1.0
    status: ApprovalStatus = ApprovalStatus.PENDING
    timeout_seconds: float = 3600.0
    created_at: datetime
    resolved_at: Optional[datetime] = None
    approver: str = ""
    reason: str = ""
```

### ApprovalStatus

```python
class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
```

---

## ConflictChecker 类

```python
class ConflictChecker:
    async def check_conflict(
        self,
        new_content: str,
        existing_memories: list[Memory],
    ) -> tuple[bool, list[str]]
    """
    检查新知识与已有知识是否冲突
    返回: (has_conflict, conflict_details)
    """
```

---

## CredentialPool 类

```python
class CredentialPool:
    def get(self, key: str) -> str
    """获取凭证（自动解密）"""

    def set(self, key: str, value: str) -> None
    """存储凭证（自动加密）"""

    def has(self, key: str) -> bool
    """检查凭证是否存在"""
```
