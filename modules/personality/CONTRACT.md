# 人格算法 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## PIDController 类

```python
@dataclass
class PIDConfig:
    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.05
    setpoint: float = 0.5
    output_min: float = 0.0
    output_max: float = 1.0
    integral_limit: float = 10.0

class PIDController:
    def __init__(self, config: PIDConfig = None)

    def compute(self, current_value: float, dt: float = 1.0) -> float
    """计算 PID 输出，返回 [output_min, output_max]"""

    def reset(self)
    """重置控制器状态"""

    def auto_tune(self, oscillation_period: float)
    """Ziegler-Nichols 自动调参"""
```

---

## KalmanFilter1D 类

```python
@dataclass
class KalmanConfig:
    process_noise: float = 0.01     # Q
    measurement_noise: float = 0.1  # R
    initial_estimate: float = 0.5
    initial_error: float = 1.0

class KalmanFilter1D:
    def __init__(self, config: KalmanConfig = None)

    @property
    def estimate(self) -> float
    """当前最优估计"""

    def predict(self, control_input: float = 0.0) -> float
    """预测步骤"""

    def update(self, measurement: float) -> float
    """更新步骤"""

    def filter(self, measurement: float, control_input: float = 0.0) -> float
    """完整滤波：预测 + 更新"""

    def adapt_noise(self, residual_history: list[float])
    """自适应噪声调整"""
```

---

## FuzzyController 类

```python
@dataclass
class FuzzyRule:
    name: str = ""
    conditions: dict = field(default_factory=dict)
    output_set: str = "medium"
    weight: float = 1.0

class FuzzyController:
    # 模糊集定义（三角形隶属函数参数）
    ERROR_SETS = {...}   # 5个模糊集
    DELTA_SETS = {...}   # 3个模糊集
    OUTPUT_SETS = {...}  # 5个模糊集

    def __init__(self, rules: list[FuzzyRule] = None)

    def compute(self, error: float, delta: float) -> float
    """模糊推理，返回调节量 [-1, 1]"""

    def _default_rules(self) -> list[FuzzyRule]
    """7条默认规则（LLM可动态调整）"""
```

---

## HEXACO 人格维度

| 维度 | 全称 | 值域 | 说明 |
|------|------|------|------|
| H | Honesty-Humility | [0,1] | 诚实-谦逊 |
| E | Emotionality | [0,1] | 情绪性 |
| X | eXtraversion | [0,1] | 外向性 |
| A | Agreeableness | [0,1] | 宜人性 |
| C | Conscientiousness | [0,1] | 尽责性 |
| O | Openness | [0,1] | 开放性 |

每个维度独立调节，三算法分别作用于不同维度。
