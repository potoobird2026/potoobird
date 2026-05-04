# 科学算法 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## ConfidenceThreshold — 贝叶斯置信度阈值

```python
class ConfidenceThreshold:
    BUCKET_WIDTH = 0.05            # 桶宽
    MIN_SAMPLES = 10               # 最小样本数
    INITIAL_HIGH_THRESHOLD = 0.85  # 初始高阈值
    INITIAL_LOW_THRESHOLD = 0.50   # 初始低阈值
    BAYESIAN_PRIOR = 0.5           # 贝叶斯先验

    def __init__(self)

    def update(self, confidence: float, confirmed: bool) -> None
    """用户确认/拒绝后更新贝叶斯模型"""

    @property
    def high_threshold(self) -> float
    """当前高阈值（确认率 > 0.85 的最低桶中心）"""

    @property
    def low_threshold(self) -> float
    """当前低阈值（确认率 < 0.50 的最高桶中心）"""

    def should_execute(self, confidence: float) -> bool
    """置信度高于高阈值 → True"""

    def should_clarify(self, confidence: float) -> bool
    """置信度低于低阈值 → True"""

    def should_confirm(self, confidence: float) -> bool
    """置信度在中间地带 → True"""
```

---

## ClarificationBudget — 边际效益追问预算

```python
class ClarificationBudget:
    def __init__(self, max_budget: int = 3)

    def remaining(self) -> int
    """剩余追问次数"""

    def spend(self) -> bool
    """消耗一次追问预算，返回是否成功"""

    def marginal_benefit(self) -> float
    """当前边际效益（递减）"""

    def should_stop(self) -> bool
    """边际效益低于阈值 → 停止追问"""
```

---

## ClarificationStrategy — 决策树追问策略

```python
class ClarificationStrategy:
    def __init__(self)

    def select_strategy(self, intent: Intent, history: list) -> str
    """
    选择追问策略
    返回: "open" / "confirm" / "hybrid" / "none"
    """

    def generate_question(self, strategy: str, intent: Intent) -> str
    """根据策略生成追问问题"""
```

---

## LogisticGrowth — Logistic 增长模型

```python
class LogisticGrowth:
    """
    用于人格参数的平滑调整
    公式: f(t) = L / (1 + e^(-k(t-t0)))
    L = 上限, k = 增长率, t0 = 中点
    """

    def __init__(self, L: float = 100.0, k: float = 0.1, t0: float = 50.0)

    def value_at(self, t: float) -> float
    """计算 t 时刻的值"""

    def adjust(self, current: float, target: float, step: float) -> float
    """向目标值平滑调整一步"""
```

---

## 算法使用位置

| 算法 | 使用模块 | 调用位置 |
|------|----------|----------|
| ConfidenceThreshold | understanding | `UnderstandingEngine.parse()` |
| ClarificationBudget | understanding | `UnderstandingEngine.generate_clarification()` |
| ClarificationStrategy | understanding | `UnderstandingEngine.generate_clarification()` |
| LogisticGrowth | understanding / personality | 人格参数平滑调整 |
| PID Controller | memory | `MemoryManager.adjust_personality()` |
| ContextCompressor | context / session | `SessionManager.on_message()` |
| ResultVerifier | delivery | `ResultVerifier.verify()` |
