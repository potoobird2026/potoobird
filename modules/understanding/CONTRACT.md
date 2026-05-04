# 理解层 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## UnderstandingEngine 类

### 构造函数

```python
class UnderstandingEngine:
    def __init__(self, llm_provider=None)
    # llm_provider: V1 可为 None，V2 必须传入
```

### 核心方法

#### 解析意图

```python
async def parse(
    self,
    user_input: str,        # 用户原始输入
    context: dict = None,   # 记忆上下文 {personality, relevant_memories, standards}
) -> Intent
```

#### 判断是否需要 LLM

```python
def should_call_llm(self, user_input: str) -> bool
# 本地规则能处理 → False；其他 → True
```

#### 生成追问

```python
def generate_clarification(
    self,
    user_input: str,
    intent: Intent,
) -> ClarificationResult
```

#### 人格反馈解析

```python
def parse_personality_feedback(
    self,
    feedback: str,          # 如 "太啰嗦了"
) -> tuple[str, str, float]
# 返回: (dimension, direction, intensity)
# 如: ("X", "decrease", 0.5)
```

---

## 数据模型

### Intent

```python
@dataclass
class Intent:
    type: str = ""                    # memory_write/memory_read/memory_search/personality_update/llm_chat/unknown
    content: str = ""                 # 原始输入
    target_layer: str = "core"        # personality/core/standard
    confidence: float = 0.0           # 0.0~1.0
    requires_approval: bool = False   # 是否需要审批
    metadata: dict = field(default_factory=dict)
    needs_clarification: bool = False # V2 追问相关
    clarification_question: str = ""
    clarification_strategy: str = "none"  # none/open/confirm/hybrid
```

### ClarificationResult

```python
@dataclass
class ClarificationResult:
    question: str = ""
    original_input: str = ""
    attempts: int = 0
    max_attempts: int = 3
```

---

## 本地规则表（LOCAL_RULES）

| 输入 | 意图类型 |
|------|----------|
| "停" | interrupt |
| "退出" | exit |
| "帮助" | help |
| "你是谁" | who_are_you |
| "现在几点" | current_time |
| "清空记忆" | clear_memory |
| "重置人格" | reset_personality |
| "查看记忆" | show_memory |
| "查看人格" | show_personality |
