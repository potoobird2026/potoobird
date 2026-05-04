"""
追问策略选择器 — 决策树模型（V2）

科学依据：
- 决策树（Decision Tree）：根据特征选择最优追问策略
- 信息增益（Information Gain）：选择能最大化减少不确定性的追问方式

追问策略类型：
1. open: 开放追问 — "你想做什么？"（信息增益最大，但用户负担重）
2. confirm: 确认追问 — "你是想 X 吗？"（信息增益中等，用户负担轻）
3. hybrid: 混合追问 — 先确认再开放（平衡策略）
4. none: 不追问 — 置信度足够高

V2 设计原则：
- 不写死追问策略（V1 固定用 open）
- 由 LLM 根据不确定性类型选择最优策略
- 决策树：根据置信度区间 + 不确定性类型 + 用户偏好选择策略

参考：02_理解层设计.md V2 升级方向 — 决策树追问策略
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("long_agent.algorithms.clarification_strategy")


class ClarificationType:
    """追问策略类型"""
    NONE = "none"           # 不追问
    CONFIRM = "confirm"     # 确认追问
    OPEN = "open"           # 开放追问
    HYBRID = "hybrid"       # 混合追问


@dataclass
class StrategyDecision:
    """策略决策结果"""
    strategy: str = ClarificationType.NONE
    question: str = ""
    reason: str = ""
    expected_gain: float = 0.0
    confidence_after: float = 0.0


class ClarificationStrategy:
    """
    追问策略选择器 — 决策树模型

    决策树逻辑：
    1. 置信度 >= 高阈值 → none（不追问，直接执行）
    2. 置信度 >= 中阈值 → confirm（确认追问，低成本）
    3. 置信度 >= 低阈值 → hybrid（混合追问）
    4. 置信度 < 低阈值 → open（开放追问，最大化信息增益）

    阈值不写死，由 LLM 根据任务风险等级动态评估。

    参数来源：
    - high_threshold: 由 LLM 评估（默认 0.8）
    - medium_threshold: 由 LLM 评估（默认 0.5）
    - low_threshold: 由 LLM 评估（默认 0.3）
    """

    # 默认阈值（仅当 LLM 未覆盖时使用）
    DEFAULT_HIGH_THRESHOLD = 0.8
    DEFAULT_MEDIUM_THRESHOLD = 0.5
    DEFAULT_LOW_THRESHOLD = 0.3

    def __init__(
        self,
        high_threshold: float = None,
        medium_threshold: float = None,
        low_threshold: float = None,
    ):
        self.high_threshold = high_threshold if high_threshold is not None else self.DEFAULT_HIGH_THRESHOLD
        self.medium_threshold = medium_threshold if medium_threshold is not None else self.DEFAULT_MEDIUM_THRESHOLD
        self.low_threshold = low_threshold if low_threshold is not None else self.DEFAULT_LOW_THRESHOLD

    def select_strategy(
        self,
        confidence: float,
        candidate_intents: list[str] = None,
        user_preference: str = None,
    ) -> StrategyDecision:
        """
        选择追问策略（决策树）

        决策树：
        ┌─ confidence >= high_threshold → none
        ├─ confidence >= medium_threshold → confirm（如果有候选意图）
        │                                  → hybrid（如果无候选意图）
        ├─ confidence >= low_threshold → hybrid
        └─ confidence < low_threshold → open

        Args:
            confidence: 当前置信度 ∈ [0, 1]
            candidate_intents: 候选意图列表，用于确认追问
            user_preference: 用户偏好 — "brief"(偏好简洁) / "detailed"(偏好详细) / None

        Returns:
            StrategyDecision
        """
        # 根据用户偏好调整阈值
        high, medium, low = self._adjust_thresholds(user_preference)

        # 决策树
        if confidence >= high:
            return StrategyDecision(
                strategy=ClarificationType.NONE,
                question="",
                reason=f"置信度 {confidence:.2f} >= 高阈值 {high:.2f}，无需追问",
                expected_gain=0.0,
                confidence_after=confidence,
            )

        if confidence >= medium:
            if candidate_intents:
                # 有候选意图 → 确认追问
                question = self._build_confirm_question(candidate_intents)
                return StrategyDecision(
                    strategy=ClarificationType.CONFIRM,
                    question=question,
                    reason=f"置信度 {confidence:.2f} ∈ [{medium:.2f}, {high:.2f})，有候选意图，使用确认追问",
                    expected_gain=0.3,
                    confidence_after=min(1.0, confidence + 0.3),
                )
            else:
                # 无候选意图 → 混合追问
                return StrategyDecision(
                    strategy=ClarificationType.HYBRID,
                    question="你想做什么？是" + "、".join(candidate_intents[:3]) + "还是其他？",
                    reason=f"置信度 {confidence:.2f} ∈ [{medium:.2f}, {high:.2f})，无候选意图，使用混合追问",
                    expected_gain=0.4,
                    confidence_after=min(1.0, confidence + 0.4),
                )

        if confidence >= low:
            return StrategyDecision(
                strategy=ClarificationType.HYBRID,
                question="我没完全理解，能具体说说吗？",
                reason=f"置信度 {confidence:.2f} ∈ [{low:.2f}, {medium:.2f})，使用混合追问",
                expected_gain=0.5,
                confidence_after=min(1.0, confidence + 0.5),
            )

        # 置信度很低 → 开放追问
        return StrategyDecision(
            strategy=ClarificationType.OPEN,
            question="你想让我做什么？请具体说明。",
            reason=f"置信度 {confidence:.2f} < 低阈值 {low:.2f}，使用开放追问",
            expected_gain=0.6,
            confidence_after=min(1.0, confidence + 0.6),
        )

    def _adjust_thresholds(self, user_preference: str = None) -> tuple[float, float, float]:
        """
        根据用户偏好调整阈值

        - "brief" 用户：降低阈值（少追问）
        - "detailed" 用户：提高阈值（多追问）
        - None：使用默认阈值
        """
        high = self.high_threshold
        medium = self.medium_threshold
        low = self.low_threshold

        if user_preference == "brief":
            # 偏好简洁：提高阈值（更不容易追问）
            high = min(0.95, high + 0.05)
            medium = min(0.85, medium + 0.1)
            low = min(0.5, low + 0.1)
        elif user_preference == "detailed":
            # 偏好详细：降低阈值（更容易追问）
            high = max(0.6, high - 0.05)
            medium = max(0.3, medium - 0.1)
            low = max(0.15, low - 0.1)

        return high, medium, low

    def _build_confirm_question(self, candidate_intents: list[str]) -> str:
        """构建确认追问问题"""
        if not candidate_intents:
            return "你想做什么？"
        if len(candidate_intents) == 1:
            return f"你是想{candidate_intents[0]}吗？"
        options = "、".join(candidate_intents[:3])
        return f"你是想{options}中的哪一个？"
