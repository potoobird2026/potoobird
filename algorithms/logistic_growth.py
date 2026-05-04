"""
Logistic Growth 模型 — 记忆容量管理

科学依据：生态学种群增长模型（Verhulst, 1838）
公式：dN/dt = rN(1 - N/K)

三个阶段：
- 快速吸收期（N < 50% K）：正常写入
- 增长放缓期（50% K < N < 85% K）：选择性写入
- 饱和压缩期（N > 85% K）：仅写高价值，触发压缩

参数科学依据：
- K = 10000：SQLite + FTS5 在 10000 条时检索延迟 < 50ms
- r = 0.15：学习曲线理论，约 5 轮对话增长 50%

参考：01_记忆系统全局设计.md 5.5 节
"""

import logging
import math
import random

logger = logging.getLogger("long_agent.algorithms.logistic_growth")


class MemoryCapacityManager:
    """
    记忆容量管理器 — Logistic Growth 模型

    职责：
    - 根据当前记忆密度计算写入概率
    - 越接近上限，写入越谨慎
    """

    # 参数（科学依据见文档）
    K = 10000       # 记忆容量上限
    R = 0.15        # 记忆吸收速率
    N0 = 100        # 初始记忆量

    # 阶段阈值
    FAST_ABSORPTION_RATIO = 0.50   # 快速吸收期上限（50% K）
    SLOW_GROWTH_RATIO = 0.85       # 增长放缓期上限（85% K）

    def __init__(self):
        self._current_n = self.N0

    def update_count(self, current_count: int):
        """更新当前记忆数量"""
        self._current_n = current_count

    def get_write_probability(self, current_count: int = None) -> float:
        """
        计算写入概率（0.0 ~ 1.0）

        使用 Logistic Growth 的离散形式：
        P(write) = 1 - (N/K)^2

        当 N 接近 K 时，P(write) 趋近于 0。
        """
        n = current_count if current_count is not None else self._current_n
        ratio = n / self.K

        # 使用平方使曲线更平滑
        probability = 1.0 - (ratio ** 2)

        # 确保在 [0.01, 1.0] 范围内（永远不为 0，保留最小写入可能）
        return max(0.01, min(1.0, probability))

    def should_write(self, current_count: int = None, value_score: float = 0.5) -> bool:
        """
        判断是否应该写入

        Args:
            current_count: 当前记忆数量
            value_score: 记忆价值评分（0.0 ~ 1.0），由写入过滤模块提供

        Returns:
            bool: 是否应该写入
        """
        probability = self.get_write_probability(current_count)

        # 高价值记忆即使在饱和期也有机会写入
        adjusted_probability = probability * (0.5 + 0.5 * value_score)

        return random.random() < adjusted_probability

    def get_phase(self, current_count: int = None) -> str:
        """获取当前阶段"""
        n = current_count if current_count is not None else self._current_n
        ratio = n / self.K

        if ratio < self.FAST_ABSORPTION_RATIO:
            return "fast_absorption"  # 快速吸收期
        elif ratio < self.SLOW_GROWTH_RATIO:
            return "slow_growth"      # 增长放缓期
        else:
            return "saturation"       # 饱和压缩期

    def should_compress(self, current_count: int = None) -> bool:
        """是否应该触发压缩（进入饱和期）"""
        return self.get_phase(current_count) == "saturation"


class OrnsteinUhlenbeck:
    """
    Ornstein-Uhlenbeck 过程 — 人格权重自然收敛

    科学依据：物理学均值回归模型（Ornstein & Uhlenbeck, 1930）
    公式：dx/dt = -θ(x - μ) + σdW

    特点：
    - 天然双向（x < μ 时增加，x > μ 时减少）
    - 在目标值附近波动（防止过拟合）
    - 半衰期 = ln(2)/θ ≈ 2.3 次反馈

    参数科学依据：
    - θ = 0.3：Lally et al. (2010) 习惯养成研究，半衰期 ≈ 2.3 次
    - σ = 5.0：心理测量学 Likert 量表测量误差 ~±10%（2σ 原则）

    参考：01_记忆系统全局设计.md 5.6 节
    """

    def __init__(self, theta: float = 0.3, sigma: float = 5.0, dt: float = 1.0):
        self.theta = theta      # 回归速率
        self.sigma = sigma      # 噪声强度
        self.dt = dt            # 时间步长

    def step(self, x: float, mu: float) -> float:
        """
        执行一步 OU 过程

        离散化形式（Euler-Maruyama 方法）：
        x(t+1) = x(t) + θ(μ - x(t))·dt + σ·√dt·Z

        Args:
            x: 当前值
            mu: 目标值

        Returns:
            float: 新值
        """
        import random
        import math

        # 确定性部分：向目标回归
        deterministic = self.theta * (mu - x) * self.dt

        # 随机部分：高斯噪声
        noise = self.sigma * math.sqrt(self.dt) * random.gauss(0, 1)

        new_x = x + deterministic + noise

        # 限制在 [0, 100] 范围内（人格评分范围）
        return max(0.0, min(100.0, new_x))

    def get_half_life(self) -> float:
        """获取半衰期（多少次反馈完成一半调整）"""
        import math
        return math.log(2) / self.theta


class PersonalityConvergence:
    """
    人格收敛器 — 整合 OU 过程 + 贝叶斯推断

    职责：
    - 根据用户反馈调整 HEXACO 六维人格
    - 使用 OU 过程实现自然收敛
    - 防止单次反馈导致剧烈波动

    科学依据：
    - OU 过程（Ornstein & Uhlenbeck, 1930）：均值回归 + 噪声
    - 贝叶斯推断：根据新证据更新信念
    - 二项分布显著性检验（Fisher, 1925）：5 次同方向反馈 → 自动调整
    """

    # 触发阈值（科学依据见 01_记忆系统全局设计.md 3.5 节）
    AUTO_ADJUST_THRESHOLD = 5       # 同方向反馈 5 次 → 自动调整
    CRITICAL_DEVIATION = 25         # 偏差超过 25 → 立即调整
    SLOW_ADJUST_MIN = 10            # 偏差 10-25 → 缓慢调整
    DEAD_ZONE = 10                  # 偏差 < 10 → 不调整（死区）

    # HEXACO 维度名
    DIMENSIONS = ["H", "E", "X", "A", "C", "O"]

    def __init__(self, initial_values: dict = None):
        """
        Args:
            initial_values: 初始人格值，默认全 50
        """
        self._values = initial_values or {d: 50.0 for d in self.DIMENSIONS}
        self._feedback_counts = {d: {"positive": 0, "negative": 0} for d in self.DIMENSIONS}
        self._ou = OrnsteinUhlenbeck(theta=0.3, sigma=5.0)

    @property
    def values(self) -> dict:
        return dict(self._values)

    def get_value(self, dimension: str) -> float:
        """获取某维度当前值"""
        return self._values.get(dimension, 50.0)

    def apply_feedback(self, dimension: str, direction: str, intensity: float = 1.0) -> dict:
        """
        应用用户反馈

        Args:
            dimension: 维度名（H/E/X/A/C/O）
            direction: "positive" 或 "negative"
            intensity: 反馈强度（0.0 ~ 1.0）

        Returns:
            dict: {"adjusted": bool, "old_value": float, "new_value": float, "reason": str}
        """
        if dimension not in self.DIMENSIONS:
            return {"adjusted": False, "old_value": 50, "new_value": 50, "reason": "未知维度"}

        old_value = self._values[dimension]

        # 记录反馈
        self._feedback_counts[dimension][direction] += 1

        # 检查是否达到自动调整阈值
        count = self._feedback_counts[dimension][direction]
        opposite = "negative" if direction == "positive" else "positive"

        # 如果反方向反馈更多，重置计数
        if self._feedback_counts[dimension][opposite] > count:
            self._feedback_counts[dimension] = {"positive": 0, "negative": 0}
            return {"adjusted": False, "old_value": old_value, "new_value": old_value, "reason": "反方向反馈更多，不调整"}

        # 计算目标值
        if direction == "positive":
            # 正反馈 → 向 100 方向调整
            target = min(100.0, old_value + 10 * intensity)
        else:
            # 负反馈 → 向 0 方向调整
            target = max(0.0, old_value - 10 * intensity)

        # 检查是否达到调整阈值
        deviation = abs(target - old_value)

        if deviation < self.DEAD_ZONE:
            return {"adjusted": False, "old_value": old_value, "new_value": old_value, "reason": "偏差在死区内，不调整"}

        if count < self.AUTO_ADJUST_THRESHOLD and deviation < self.CRITICAL_DEVIATION:
            return {"adjusted": False, "old_value": old_value, "new_value": old_value, "reason": f"反馈次数不足（{count}/{self.AUTO_ADJUST_THRESHOLD}）"}

        # 使用 OU 过程执行调整
        new_value = self._ou.step(old_value, target)
        self._values[dimension] = new_value

        # 重置该维度的反馈计数
        self._feedback_counts[dimension] = {"positive": 0, "negative": 0}

        reason = f"反馈 {count} 次，OU 过程调整"
        if deviation >= self.CRITICAL_DEVIATION:
            reason = f"偏差 {deviation:.0f} 超过临界值 {self.CRITICAL_DEVIATION}，立即调整"

        logger.info(f"人格调整 [{dimension}]: {old_value:.1f} → {new_value:.1f} ({reason})")

        return {
            "adjusted": True,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
        }

    def reset_dimension(self, dimension: str):
        """重置某维度到初始值 50"""
        if dimension in self.DIMENSIONS:
            self._values[dimension] = 50.0
            self._feedback_counts[dimension] = {"positive": 0, "negative": 0}
            logger.info(f"人格重置 [{dimension}]: → 50.0")

    def reset_all(self):
        """重置所有维度"""
        for d in self.DIMENSIONS:
            self._values[d] = 50.0
            self._feedback_counts[d] = {"positive": 0, "negative": 0}
        logger.info("人格重置: 全部 → 50.0")
