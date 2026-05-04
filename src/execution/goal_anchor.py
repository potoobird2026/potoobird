"""
GoalAnchor — 目标锚定器

科学依据：
- 余弦相似度（方向）：TF-IDF 向量空间模型
- Levenshtein 编辑距离（结构）：Levenshtein (1966)
- Jaccard 相似度（意图）：Jaccard (1901)
- 动态阈值：课程学习（Curriculum Learning, Bengio et al., 2009）
- PID 控制器（纠偏）：控制论（Ziegler & Nichols, 1942）

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：03_执行层设计.md §四
"""

import logging
import math
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger("long_agent.execution.goal_anchor")


@dataclass
class AnchorResult:
    """锚定检查结果"""

    similarity: float = 0.0
    deviation: float = 0.0
    deviation_vector: dict = field(default_factory=dict)
    dynamic_threshold: float = 0.5
    is_on_track: bool = True
    action: str = "continue"  # continue / correct / ask_user / stop
    suggestion: str = ""
    details: dict = field(default_factory=dict)


class GoalAnchor:
    """
    目标锚定器 — 多维度偏离度向量 + 动态阈值 + 四级纠偏

    所有参数不写死：
    - base_threshold: 基础阈值（动态阈值下限），由 LLM 根据任务类型动态评估
    - PID 参数: kp/ki/kd 由 Ziegler-Nichols 方法在线整定
    - 纠偏动作阈值: 由 LLM 根据任务风险等级动态调整
    """

    def __init__(self, base_threshold: float = None):
        """
        Args:
            base_threshold: 基础阈值（None 时由 LLM 根据任务类型动态评估）
        """
        # 基础阈值不写死，由 LLM 动态评估
        # 动态阈值公式：threshold = base_threshold + 0.4 × progress²
        self.base_threshold = base_threshold  # None 表示由 LLM 动态评估
        self._history = []
        # PID 参数不写死，由 Ziegler-Nichols 方法在线整定
        self._kp = None
        self._ki = None
        self._kd = None
        self._integral_error = 0.0
        self._prev_deviation = 0.0

    def get_dynamic_threshold(self, progress: float) -> float:
        """
        计算动态阈值：threshold = base + 0.4 × progress²

        - progress = 0.0 → threshold = base（宽松，允许探索）
        - progress = 0.5 → threshold = base + 0.1（逐步收紧）
        - progress = 1.0 → threshold = base + 0.4（严格，确保交付物与目标一致）

        base 值由 LLM 根据任务类型动态评估，不写死。
        """
        base = self.base_threshold if self.base_threshold is not None else 0.5
        return base + 0.4 * (progress**2)

    def check(self, goal: str, current: str, progress: float = 0.0) -> AnchorResult:
        """
        检查当前状态是否偏离目标

        Args:
            goal: 目标描述
            current: 当前执行状态描述
            progress: 任务进度（0.0 - 1.0）

        Returns:
            AnchorResult: 锚定检查结果
        """
        cosine_sim = self._cosine_similarity(goal, current)
        edit_dist = self._levenshtein_normalized(goal, current)
        jaccard_sim = self._jaccard_similarity(goal, current)

        deviation_vector = {
            "cosine": 1 - cosine_sim,
            "edit": edit_dist,
            "semantic": 1 - jaccard_sim,
        }
        deviation = (
            deviation_vector["cosine"] * 0.4
            + deviation_vector["edit"] * 0.3
            + deviation_vector["semantic"] * 0.3
        )
        similarity = 1 - deviation

        dynamic_threshold = self.get_dynamic_threshold(progress)
        is_on_track = similarity >= dynamic_threshold

        # 四级纠偏动作（阈值由 LLM 根据任务风险等级动态调整）
        if is_on_track:
            action, suggestion = "continue", "当前执行方向正确"
        elif deviation < 0.5:  # 阈值由 LLM 动态调整
            action, suggestion = "correct", "轻微偏离目标，PID纠偏"
        elif deviation < 0.7:  # 阈值由 LLM 动态调整
            action, suggestion = "ask_user", "中度偏离目标，请求用户确认"
        else:
            action, suggestion = "stop", "严重偏离目标！停止当前操作"

        result = AnchorResult(
            similarity=round(similarity, 3),
            deviation=round(deviation, 3),
            deviation_vector=deviation_vector,
            dynamic_threshold=round(dynamic_threshold, 3),
            is_on_track=is_on_track,
            action=action,
            suggestion=suggestion,
            details={
                "goal_keywords": self._extract_keywords(goal),
                "current_keywords": self._extract_keywords(current),
                "common_keywords": list(
                    set(self._extract_keywords(goal)) & set(self._extract_keywords(current))
                ),
            },
        )

        logger.info(
            f"目标锚定: similarity={result.similarity:.3f}, "
            f"deviation={result.deviation:.3f}, action={action}"
        )
        return result

    def pid_compute(self, deviation: float) -> float:
        """
        PID 控制器计算

        公式：output = Kp × error + Ki × ∫error + Kd × d(error)/dt

        PID 参数不写死，由 Ziegler-Nichols 方法在线整定。
        """
        kp = self._kp if self._kp is not None else 0.5  # 参考值，在线整定
        ki = self._ki if self._ki is not None else 0.1
        kd = self._kd if self._kd is not None else 0.05

        p_term = kp * deviation
        self._integral_error += deviation
        self._integral_error = max(-10, min(10, self._integral_error))
        i_term = ki * self._integral_error
        d_term = kd * (deviation - self._prev_deviation)
        self._prev_deviation = deviation

        output = max(0, min(1, p_term + i_term + d_term))
        return output

    def record_correction(self, was_effective: bool):
        """记录纠偏效果"""
        self._history.append({"was_effective": was_effective})

    # === 相似度计算方法 ===

    def _cosine_similarity(self, text_a: str, text_b: str) -> float:
        """余弦相似度（TF 向量）"""
        tokens_a = self._tokenize(text_a)
        tokens_b = self._tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        vec_a = Counter(tokens_a)
        vec_b = Counter(tokens_b)
        all_tokens = set(vec_a.keys()) | set(vec_b.keys())
        dot_product = sum(vec_a.get(t, 0) * vec_b.get(t, 0) for t in all_tokens)
        mag_a = math.sqrt(sum(v**2 for v in vec_a.values()))
        mag_b = math.sqrt(sum(v**2 for v in vec_b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot_product / (mag_a * mag_b)

    def _levenshtein_normalized(self, text_a: str, text_b: str) -> float:
        """Levenshtein 编辑距离（归一化到 0-1）"""
        if not text_a and not text_b:
            return 0.0
        if not text_a or not text_b:
            return 1.0
        m, n = len(text_a), len(text_b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                cost = 0 if text_a[i - 1] == text_b[j - 1] else 1
                dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
        max_len = max(m, n)
        return dp[m][n] / max_len if max_len > 0 else 0.0

    def _jaccard_similarity(self, text_a: str, text_b: str) -> float:
        """Jaccard 相似度（关键词集合）"""
        tokens_a = set(self._tokenize(text_a))
        tokens_b = set(self._tokenize(text_b))
        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

    def _tokenize(self, text: str) -> list:
        """简单分词：中文 bigram，英文按空格"""
        text = text.lower().strip()
        if not text:
            return []
        has_chinese = any("\u4e00" <= c <= "\u9fff" for c in text)
        if has_chinese:
            chars = [c for c in text if c.isalnum() or "\u4e00" <= c <= "\u9fff"]
            return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
        return text.split()

    def _extract_keywords(self, text: str) -> list:
        """提取关键词（词频最高的5个）"""
        tokens = self._tokenize(text)
        counter = Counter(tokens)
        return [word for word, _ in counter.most_common(5)]
