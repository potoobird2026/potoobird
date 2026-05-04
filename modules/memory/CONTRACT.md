# 记忆系统 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-04
> **对齐**：以 `src/memory/manager.py` 实际代码为准，已删除不存在的 MemoryStorage/MemoryWriteResult/Memory 抽象层

---

## MemoryManager 类

### 构造函数

```python
class MemoryManager:
    def __init__(
        self,
        storage,                    # 存储目录路径（str）
        data_dir: str,              # 数据目录路径
        audit_logger: AuditLogger = None,  # 审计日志器
        read_only: bool = False,    # 只读模式
        context_window: int = 8192, # 上下文窗口大小
        capacity_k: int = 100,      # LogisticGrowth K 值
        compressor: ContextCompressor = None,  # 上下文压缩器（V2）
        alpha: float = 0.1,         # LogisticGrowth 增长率
    )
```

### 核心方法

#### 写入记忆

```python
async def remember(
    self,
    content: str,           # 记忆内容
    layer: str = "core",    # 层级：personality / core / standard
    category: str = "general",  # 分类标签
) -> dict                  # 返回 {"success": bool, "memory_id": str, ...}
```

#### 读取记忆

```python
async def recall(
    self,
    query: str,             # 查询内容（用于相关性排序）
    layer: str = "core",
    limit: int = 50,
) -> list                 # 返回记忆列表
```

#### 搜索记忆

```python
async def search(
    self,
    query: str,
    layer: str = "core",
    limit: int = 10,
) -> list                 # 返回匹配的记忆列表
```

#### 获取人格

```python
def get_personality(self) -> dict
# 返回: {"H": 70, "E": 40, "X": 60, "A": 55, "C": 80, "O": 65}
```

#### 获取标准（V2 新增）

```python
async def get_standards(
    self,
    category: str = None,
    limit: int = 50,
) -> dict                # 返回第3层标准，组装为字典供 Prompt 使用
```

#### 构建上下文（V2 新增）

```python
async def build_context(self) -> str
# 组装人格 + 核心记忆 + 标准，生成 Prompt 可用的上下文文本
```

#### 人格调整（PID）

```python
def adjust_personality(
    self,
    adjustments: dict,      # {"H": delta, "E": delta, ...}
) -> dict                  # 返回调整后的人格
```

#### 记忆加载（V2 新增）

```python
async def load_memories_for_context(
    self,
    current_input: str,     # 当前用户输入
    layer_filter: list = None,  # 层级过滤
) -> list                  # 返回按相关性排序的记忆列表
```

#### 容量检查与淘汰（V2 新增）

```python
async def check_and_evict(
    self,
    current_input: str,     # 当前输入（用于计算相关性）
) -> dict                  # 返回淘汰结果 {"evicted": int, "remaining": int}

def get_capacity_status(self) -> dict
# 返回容量状态 {"current": int, "k": int, "usage_pct": float}
```

#### Prompt 组装（V2 新增）

```python
def build_system_prompt_memories(
    self,
    current_input: str,
    layer_order: list = None,
) -> str                   # 返回组装好的 Prompt 文本
```

#### 维护方法

```python
async def decay_access_counts(self, factor: float = 0.95) -> None
# 访问计数衰减（定期调用）

async def should_compress_cold_zone(self) -> bool
# 检查是否需要压缩冷区

async def compress_cold_zone(self) -> dict
# 压缩冷区记忆

def backup(self, keep: int = 5) -> str
# 备份数据库，返回备份路径

def save_personality(self) -> None
# 持久化人格到 personality.md

def close(self) -> None
# 关闭数据库连接
```

---

## 异常定义

```python
class PersonalitySchemaError(Exception):
    """personality.md Schema 校验错误"""
    pass
```

---

## 依赖说明

- **存储层**：`src/memory/storage/` 目录下的 SQLite 实现（无抽象层）
- **审计日志**：`src/audit.logger.AuditLogger`
- **压缩器**：`src.context.compressor.ContextCompressor`（V2 注入）

---

## 变更记录

| 日期 | 变更内容 |
|------|----------|
| 2026-05-03 | 初版创建 |
| 2026-05-04 | 对齐实际代码：删除 MemoryStorage/MemoryWriteResult/Memory 不存在的抽象层，补全 V2 新增方法签名 |
