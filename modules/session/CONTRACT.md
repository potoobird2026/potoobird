# 会话管理 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## SessionManager 类

### 构造函数

```python
class SessionManager:
    def __init__(self, idle_timeout: int = None)
    # idle_timeout: 默认 3600 秒，运行后自适应
```

### 会话 CRUD

```python
async def create_session(
    self,
    conversation_id: str = "",
    user_id: str = "default",
    context: dict = None,
) -> Session
"""创建新会话"""

async def get_session(self, session_id: str) -> Optional[Session]
"""获取会话（自动更新活跃时间）"""

async def save_session(self, session_id: str) -> bool
"""持久化会话"""

async def destroy_session(self, session_id: str) -> None
"""销毁会话"""

async def list_sessions(self, user_id: str = None) -> list[Session]
"""列出用户的所有会话"""

async def cleanup_expired(self) -> int
"""清理过期会话，返回清理数量"""
```

---

## Session 数据类

```python
@dataclass
class Session:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    conversation_id: str = ""
    user_id: str = "default"
    state: str = "active"   # active / idle / expired / closed
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    context: dict = field(default_factory=dict)
    message_count: int = 0
    metadata: dict = field(default_factory=dict)
```

---

## IdentityManager 类

```python
class IdentityManager:
    def __init__(self, data_dir: str = "data")

    async def get_user(self, user_id: str) -> dict
    """获取用户信息"""

    async def create_user(self, user_id: str, config: dict = None) -> dict
    """创建用户"""

    async def update_user(self, user_id: str, updates: dict) -> dict
    """更新用户配置"""

    async def list_users(self) -> list[str]
    """列出所有用户ID"""
```

---

## EventBus 类

```python
class EventBus:
    def __init__(self)

    def subscribe(self, event_type: str, handler: Callable) -> None
    """订阅事件"""

    def unsubscribe(self, event_type: str, handler: Callable) -> None
    """取消订阅"""

    async def publish(self, event_type: str, data: dict = None) -> None
    """发布事件（异步）"""

    async def publish_sync(self, event_type: str, data: dict = None) -> None
    """发布事件（同步）"""
```

---

## 事件类型清单

| 事件类型 | 触发时机 | 数据 |
|----------|----------|------|
| `session.created` | 新会话创建 | `{session_id, user_id}` |
| `session.expired` | 会话过期 | `{session_id}` |
| `session.closed` | 会话关闭 | `{session_id}` |
| `message.received` | 收到用户消息 | `{session_id, content}` |
| `message.sent` | 发送回复 | `{session_id, content}` |
| `intent.parsed` | 意图解析完成 | `{intent, confidence}` |
| `execution.started` | 执行开始 | `{task_id}` |
| `execution.completed` | 执行完成 | `{task_id, result}` |
| `execution.failed` | 执行失败 | `{task_id, error}` |
| `verification.passed` | 验证通过 | `{task_id, report}` |
| `verification.failed` | 验证失败 | `{task_id, report}` |
