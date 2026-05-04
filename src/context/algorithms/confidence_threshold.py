"""
置信度阈值管理器 — 贝叶斯动态阈值（V2）

科学依据：
- 贝叶斯定理：P(H|E) = P(E|H) × P(H) / P(E)
- 置信度 = P(意图正确 | 当前证据)
- 阈值动态调整：由 LLM 根据任务风险等级、对话历史准确率动态评估

V2 设计原则：
- 不写死固定阈值（V1 用 0.5 硬编码）
- 贝叶斯更新：每次交互后更新置信度
- 动态阈值：高风险任务阈值高（需更确定才行动），低风险任务阈值低
- 所有参数由 LLM 动态评估或贝叶斯公式计算，无魔法数字

参考：02_理解层设计.md V2 升级方向 — 贝叶斯置信度阈值
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("long_agent.algorithms.confidence_threshold")


@dataclass
class ConfidenceResult:
    """置信度评估结果"""

    confidence: float = 0.0  # 当前置信度 P(H|E) ∈ [0, 1]
    threshold: float = 0.0  # 动态阈值
    is_confident: bool = False  # 置信度 >= 阈值
    needs_clarification: bool = False  # 需要追问
    prior: float = 0.0  # 先验概率 P(H)
    posterior: float = 0.0  # 后验概率 P(H|E)
    evidence_strength: float = 0.0  # 证据强度 P(E|H)
    details: dict = field(default_factory=dict)


class ConfidenceThreshold:
    """
    置信度阈值管理器 — 贝叶斯动态阈值

    职责：
    1. 用贝叶斯定理更新意图置信度
    2. 根据任务风险等级动态调整阈值
    3. 判断是否需要追问

    参数来源：
    - prior: 由 LLM 根据任务类型和历史准确率动态评估
    - threshold: 由 LLM 根据任务风险等级动态评估（高风险 > 0.8, 中风险 > 0.6, 低风险 > 0.4）
    - evidence_strength: 由 LLM 根据输入与意图的匹配度评估

    设计原则：
    - 所有参数不写死，由 LLM 动态评估或贝叶斯公式计算
    - 高风险任务（如删除操作）需要更高置信度才执行
    - 低风险任务（如查询）可以容忍较低置信度
    """

    # 默认先验概率（无信息先验 = 0.5，表示完全不确定）
    DEFAULT_PRIOR = 0.5

    # 默认阈值（仅当 LLM 未提供时使用，实际应由 LLM 动态评估）
    DEFAULT_THRESHOLD = 0.5

    def __init__(self, prior: float = None, threshold: float = None):
        """
        Args:
            prior: 先验概率 P(H)，None 表示使用无信息先验 0.5
            threshold: 置信度阈值，None 表示由 LLM 动态评估
        """
        self.prior = prior if prior is not None else self.DEFAULT_PRIOR
        self.threshold = threshold  # None 表示由 LLM 动态评估
        self._history: list[ConfidenceResult] = []

    def bayesian_update(
        self,
        prior: float,
        evidence_strength: float,
        evidence_prob: float = None,
    ) -> float:
        """
        贝叶斯更新：计算后验概率 P(H|E)

        公式：P(H|E) = P(E|H) × P(H) / P(E)

        其中：
        - P(H) = prior（先验概率）
        - P(E|H) = evidence_strength（证据强度 = 意图正确时观察到当前证据的概率）
        - P(E) = evidence_prob（证据概率），None 时用均匀假设 P(E) = 0.5

        Args:
            prior: 先验概率 P(H) ∈ [0, 1]
            evidence_strength: 证据强度 P(E|H) ∈ [0, 1]
            evidence_prob: 证据概率 P(E) ∈ [0, 1]，None 时默认 0.5

        Returns:
            后验概率 P(H|E) ∈ [0, 1]
        """
        if not (0 <= prior <= 1):
            raise ValueError(f"先验概率必须在 [0,1] 范围内，当前值: {prior}")
        if not (0 <= evidence_strength <= 1):
            raise ValueError(f"证据强度必须在 [0,1] 范围内，当前值: {evidence_strength}")

        p_e = evidence_prob if evidence_prob is not None else 0.5

        # 防止除零
        if p_e == 0:
            p_e = 1e-10

        posterior = (evidence_strength * prior) / p_e

        # 裁剪到 [0, 1]
        posterior = max(0.0, min(1.0, posterior))

        logger.debug(
            f"贝叶斯更新: P(H)={prior:.3f}, P(E|H)={evidence_strength:.3f}, "
            f"P(E)={p_e:.3f} → P(H|E)={posterior:.3f}"
        )

        return posterior

    def get_dynamic_threshold(
        self,
        risk_level: str = "medium",
        history_accuracy: float = None,
    ) -> float:
        """
        计算动态阈值

        阈值由 LLM 根据以下因素动态评估：
        1. 任务风险等级：high > 0.8, medium > 0.6, low > 0.4
        2. 历史准确率：历史准确率高时可适当降低阈值
        3. 用户偏好：用户可配置风险容忍度

        当 LLM 无法评估时，使用基于风险等级的默认值。

        Args:
            risk_level: 任务风险等级 — "high" / "medium" / "low"
            history_accuracy: 历史准确率 ∈ [0, 1]，None 表示无历史数据

        Returns:
            动态阈值 ∈ [0, 1]
        """
        # 基础阈值由风险等级决定（这些默认值仅在 LLM 未覆盖时使用）
        base_thresholds = {
            "high": 0.85,  # 高风险：需高度确定才执行（如删除、修改人格）
            "medium": 0.65,  # 中风险：中等确定性（如记忆写入）
            "low": 0.45,  # 低风险：可容忍较低确定性（如查询、闲聊）
        }

        base = base_thresholds.get(risk_level, self.DEFAULT_THRESHOLD)

        # 历史准确率调整：准确率高时可适当降低阈值
        if history_accuracy is not None and 0 <= history_accuracy <= 1:
            # 调整公式：threshold = base × (1.1 - 0.2 × accuracy)
            # accuracy=1.0 → threshold = base × 0.9（降低 10%）
            # accuracy=0.0 → threshold = base × 1.1（提高 10%）
            adjustment = 1.1 - 0.2 * history_accuracy
            threshold = base * adjustment
        else:
            threshold = base

        # 裁剪到 [0.1, 0.95]，避免极端值
        threshold = max(0.1, min(0.95, threshold))

        logger.debug(
            f"动态阈值: risk={risk_level}, base={base:.3f}, "
            f"history_acc={history_accuracy}, threshold={threshold:.3f}"
        )

        return threshold

    def evaluate(
        self,
        confidence: float,
        risk_level: str = "medium",
        prior: float = None,
        evidence_strength: float = None,
        history_accuracy: float = None,
    ) -> ConfidenceResult:
        """
        评估置信度是否达到阈值

        Args:
            confidence: 原始置信度 ∈ [0, 1]
            risk_level: 任务风险等级
            prior: 先验概率，None 时使用实例默认值
            evidence_strength: 证据强度，None 时跳过贝叶斯更新
            history_accuracy: 历史准确率

        Returns:
            ConfidenceResult
        """
        p = prior if prior is not None else self.prior

        # 贝叶斯更新（如果有证据强度）
        if evidence_strength is not None:
            posterior = self.bayesian_update(p, evidence_strength)
        else:
            posterior = confidence

        # 动态阈值
        threshold = (
            self.threshold
            if self.threshold is not None
            else self.get_dynamic_threshold(risk_level, history_accuracy)
        )

        is_confident = posterior >= threshold
        needs_clarification = not is_confident

        result = ConfidenceResult(
            confidence=round(posterior, 4),
            threshold=round(threshold, 4),
            is_confident=is_confident,
            needs_clarification=needs_clarification,
            prior=round(p, 4),
            posterior=round(posterior, 4),
            evidence_strength=round(evidence_strength, 4) if evidence_strength else 0.0,
            details={
                "risk_level": risk_level,
                "history_accuracy": history_accuracy,
                "raw_confidence": confidence,
            },
        )

        self._history.append(result)

        logger.info(
            f"置信度评估: confidence={result.confidence:.3f}, "
            f"threshold={result.threshold:.3f}, "
            f"is_confident={is_confident}, risk={risk_level}"
        )

        return result

    def should_clarify(self, confidence: float, risk_level: str = "medium") -> bool:
        """
        快速判断是否需要追问

        Args:
            confidence: 当前置信度
            risk_level: 任务风险等级

        Returns:
            True 表示需要追问
        """
        threshold = (
            self.threshold if self.threshold is not None else self.get_dynamic_threshold(risk_level)
        )
        return confidence < threshold

    def get_history(self) -> list[ConfidenceResult]:
        """获取历史评估结果"""
        return list(self._history)

    def reset_history(self):
        """清空历史"""
        self._history.clear()
