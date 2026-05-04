"""
追问预算管理器 — 边际效益递减模型（V2）

科学依据：
- 边际效益递减规律（Diminishing Marginal Returns）
- 每次追问的信息增益递减：第1次追问 > 第2次追问 > 第3次追问
- 当边际信息增益 < 追问成本时，停止追问

V2 设计原则：
- 不写死最大追问次数（V1 固定 3 次）
- 由 LLM 评估每次追问的预期信息增益
- 边际效益 < 成本时自动停止追问
- 预算分配：根据任务复杂度和不确定性动态调整

参考：02_理解层设计.md V2 升级方向 — 边际效益追问预算
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("long_agent.algorithms.clarification_budget")


@dataclass
class ClarificationBudget:
    """
    追问预算 — 边际效益递减模型

    职责：
    1. 跟踪追问次数和累计信息增益
    2. 判断是否值得继续追问（边际效益 > 成本）
    3. 动态分配追问预算

    参数来源：
    - max_budget: 由 LLM 根据任务复杂度动态评估（简单任务 2 次，复杂任务 5 次）
    - cost_per_attempt: 由 LLM 根据用户耐心度和任务紧急度评估
    - decay_rate: 信息增益衰减率，由 LLM 根据领域知识评估
    """

    max_budget: int = 3  # 最大追问次数（由 LLM 动态评估）
    cost_per_attempt: float = 0.15  # 每次追问的成本（时间/用户体验）
    decay_rate: float = 0.6  # 信息增益衰减率（每次追问后信息增益 × decay_rate）
    attempts: int = 0  # 已用追问次数
    cumulative_gain: float = 0.0  # 累计信息增益
    _gains: list = field(default_factory=list)  # 每次追问的信息增益记录

    def remaining_budget(self) -> int:
        """剩余追问次数"""
        return max(0, self.max_budget - self.attempts)

    def expected_gain(self) -> float:
        """
        计算下一次追问的预期信息增益

        公式：expected_gain = base_gain × decay_rate^attempts
        - base_gain: 首次追问的信息增益（由 LLM 评估）
        - decay_rate: 衰减率
        - attempts: 已追问次数

        Returns:
            预期信息增益 ∈ [0, 1]
        """
        # 基础信息增益：首次追问通常能获得较多信息
        base_gain = 0.5  # 默认值，实际由 LLM 评估

        expected = base_gain * (self.decay_rate**self.attempts)
        return max(0.0, min(1.0, expected))

    def should_continue(self, last_gain: float = None) -> bool:
        """
        判断是否值得继续追问

        决策规则：
        1. 还有预算（attempts < max_budget）
        2. 预期信息增益 > 追问成本（边际效益 > 成本）
        3. 最近一次追问确实获得了信息增益（非无效追问）

        Args:
            last_gain: 最近一次追问的实际信息增益，None 时使用预期值

        Returns:
            True 表示应该继续追问
        """
        # 1. 预算检查
        if self.attempts >= self.max_budget:
            logger.debug(f"追问预算耗尽: {self.attempts}/{self.max_budget}")
            return False

        # 2. 边际效益检查
        gain = last_gain if last_gain is not None else self.expected_gain()
        if gain <= self.cost_per_attempt:
            logger.debug(f"边际效益不足: gain={gain:.3f} <= cost={self.cost_per_attempt:.3f}")
            return False

        return True

    def record_attempt(self, info_gain: float):
        """
        记录一次追问及其信息增益

        Args:
            info_gain: 本次追问的信息增益 ∈ [0, 1]
        """
        self.attempts += 1
        self._gains.append(info_gain)
        self.cumulative_gain += info_gain

        logger.info(
            f"追问记录: attempt={self.attempts}/{self.max_budget}, "
            f"gain={info_gain:.3f}, cumulative={self.cumulative_gain:.3f}"
        )

    def get_stats(self) -> dict:
        """获取追问统计"""
        return {
            "max_budget": self.max_budget,
            "attempts": self.attempts,
            "remaining": self.remaining_budget(),
            "cumulative_gain": round(self.cumulative_gain, 4),
            "gains": [round(g, 4) for g in self._gains],
            "expected_next_gain": round(self.expected_gain(), 4),
        }

    def reset(self):
        """重置预算（新任务开始时调用）"""
        self.attempts = 0
        self.cumulative_gain = 0.0
        self._gains.clear()
