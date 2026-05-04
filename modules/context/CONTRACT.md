# 上下文压缩 — 接口契约

> **版本**：v2.2 | **日期**：2026-05-04
> **代码**：`src/context/compressor.py`

---

## ContextCompressor 类

### 构造函数

```python
class ContextCompressor:
    def __init__(
        self,
        initial_keep: int = 200,        # 初始保留消息数（自适应）
        compression_threshold: float = 0.6,  # 压缩阈值（LLM动态评估）
        adjustment_interval: int = 100,      # 调整间隔（自适应）
    )
```

### 核心方法

```python
async def compress(
    self,
    messages: list[dict],       # 待压缩的消息列表
    current_input: str = "",    # 当前用户输入（用于相关性评分）
    max_messages: int = None,   # 最大保留消息数（默认由认知负荷公式计算）
) -> CompressResult:
    """
    压缩上下文消息（V2 统一入口：双锚点 + 10算法融合评分 + 幂律裁剪）

    流程：
    1. 双锚点保边：保留最早M条锚点 + 最近N条工作记忆
    2. 中间区域评分：10算法融合评分引擎（score_memory）
    3. 幂律裁剪：apply_power_law_pruning 裁剪低价值消息

    返回 CompressResult（V2 统一格式，9字段）
    """
```

### 评分方法（10算法）

```python
def score_memory(self, memory: dict, session_context: dict = None, current_input: str = "") -> dict:
    """对单条消息打价值分，返回 {算法名: (score, confidence)}"""

# 10个评分方法（每个返回 float 0~1）：
# _score_forgetting(memory)           — 遗忘曲线（Ebbinghaus）
# _score_access_frequency(memory)     — 访问频率
# _score_recency(memory)              — 最近度
# _score_relevance(memory, current_input) — 相关性
# _score_layer_weight(memory)         — 层权重
# _score_contradiction(memory, session_context) — 矛盾检测
# _score_topic_consistency(memory, current_input) — 话题一致性
# _score_anchor(memory, session_context) — 锚点分数
# _score_value_density(memory)        — 价值密度
# _score_power_law(memory, other_scores) — 幂律分数
```

### 裁剪方法

```python
def apply_power_law_pruning(self, scored_memories: list[dict]) -> list[dict]:
    """
    幂律裁剪低价值消息。
    输入：带评分的 dict 列表（每个 dict 含 "memory" 和 "final_score" 字段）
    输出：裁剪后的 dict 列表
    """
```

---

## 数据模型

### CompressResult（V2 统一版本，9字段）

```python
@dataclass
class CompressResult:
    summary: str = ""                    # 压缩后的摘要文本
    quality_score: float = 0.0           # LLM 自评摘要质量 (0-1)
    pruned_count: int = 0                # 裁剪掉的消息数
    kept_indices: list = field(default_factory=list)  # 保留的消息索引
    compressed_token_count: int = 0      # 节省的 token 数
    method: str = ""                     # 使用的压缩方法
    feedback_signals: dict = field(default_factory=dict)  # 反馈信号
    original_count: int = 0              # 压缩前消息总数（兼容字段）
    kept_ids: list = field(default_factory=list)  # 保留的消息ID列表（兼容字段）
    compressed_count: int = 0            # 压缩后保留的消息数（兼容字段）
```

### DualAnchorBounds

```python
@dataclass
class DualAnchorBounds:
    anchor_count: int       # 锚点消息数 M
    recent_count: int       # 最近保留窗口 N
    compressible_start: int # 可压缩区域起始索引
    compressible_end: int   # 可压缩区域结束索引
```

### CompressState（后台压缩进程状态机）

```python
class CompressState(Enum):
    SLEEP = "sleep"                 # 休眠，等待触发
    COMPRESSING = "compressing"     # 正在压缩
    MONITORING = "monitoring"       # 监控压缩后质量
    PAUSED = "paused"               # 暂停（用户干预）
```

---

## 算法清单（实际实现）

| # | 方法名 | 评分维度 | 科学依据 |
|---|--------|----------|----------|
| 1 | `_score_forgetting` | 时效性 | Ebbinghaus, 1885 |
| 2 | `_score_access_frequency` | 访问频率 | 记忆强度理论 |
| 3 | `_score_recency` | 最近度 | 近因效应 |
| 4 | `_score_relevance` | 相关性 | 余弦相似度近似 |
| 5 | `_score_layer_weight` | 层权重 | 三层记忆架构 |
| 6 | `_score_contradiction` | 矛盾检测 | 一致性检验 |
| 7 | `_score_topic_consistency` | 话题一致性 | 话题切换检测 |
| 8 | `_score_anchor` | 锚点分数 | 实体定义/关键决策 |
| 9 | `_score_value_density` | 价值密度 | 信息密度评估 |
| 10 | `_score_power_law` | 幂律分数 | Clauset et al., 2009 |

权重公式：`w_i = conf_i / Σconf_j`（置信度归一化）
