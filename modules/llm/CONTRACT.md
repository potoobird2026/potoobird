# LLM 调用层 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## ModelRouter 类

### 构造函数

```python
class ModelRouter:
    def __init__(self)
```

### 模型管理

```python
def register_model(
    self,
    name: str,              # 模型唯一标识
    provider: str,          # openai/anthropic/google/...
    model: str,             # gpt-4o/claude-3-...
    api_key: str,           # 必填，运行时从配置读取
    base_url: str = "",     # 自定义端点
    priority: int = 0,      # 0=最高，不写死
    max_retries: int = 3,   # 不写死，LLM动态评估
    timeout: int = 30,      # 不写死，LLM动态评估
) -> ModelConfig

def switch_model(self, name: str) -> ModelConfig
"""手动切换模型，模型未注册时抛 ValueError"""
```

### LLM 调用

```python
async def call(
    self,
    messages: list[dict],       # OpenAI 格式消息列表
    model_name: str = None,     # None 使用当前模型
    temperature: float = 0.7,
    max_tokens: int = 2048,
    **kwargs,
) -> LLMResult
"""带回退链 + 冷却检查的 LLM 调用"""
```

### 状态查询

```python
def get_status(self) -> dict
"""返回当前模型状态（供 UI 显示）"""
# 返回结构:
# {
#   "current_model": str,
#   "fallback_chain": list[str],
#   "models": {name: {provider, model, priority, is_in_cooldown, failure_rate, total_calls}},
#   "stats": {total_requests, total_fallbacks, total_failures}
# }
```

---

## 数据模型

### ModelConfig

```python
@dataclass
class ModelConfig:
    name: str
    provider: str
    model: str
    api_key: str
    base_url: str = ""
    priority: int = 0
    max_retries: int = 3
    timeout: int = 30
    cooldown_until: Optional[datetime] = None
    failure_count: int = 0
    total_calls: int = 0
    total_failures: int = 0

    @property
    def is_in_cooldown(self) -> bool
    @property
    def failure_rate(self) -> float
```

### RouterStats

```python
@dataclass
class RouterStats:
    total_requests: int = 0
    total_fallbacks: int = 0
    total_failures: int = 0
    model_stats: dict = field(default_factory=dict)
```

---

## PromptManager 类

### 构造函数

```python
class PromptManager:
    def __init__(self)
    # 自动注册默认模板
```

### 模板管理

```python
def register_template(self, template: PromptTemplate) -> None
def get_template(self, name: str) -> Optional[PromptTemplate]
def update_template(self, name: str, template: PromptTemplate) -> None
def list_templates(self) -> list[PromptTemplate]
```

### Prompt 组装

```python
def build_system_prompt(
    self,
    personality: dict = None,       # {"H":70, "E":40, ...}
    relevant_memories: list = None,  # 相关记忆列表
    standards: str = "",            # 当前标准文本
    user_id: str = "default",
) -> str
"""
动态组装 system prompt
注入顺序：基础信息 → 人格参数 → 相关记忆 → 当前标准
"""
```

---

## 数据模型

### PromptTemplate

```python
@dataclass
class PromptTemplate:
    name: str
    template: str
    version: str = "1.0"
    description: str = ""
    tags: list = field(default_factory=list)
```
