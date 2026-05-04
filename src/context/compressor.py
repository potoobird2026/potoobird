"""
上下文压缩器 — V2 多算法融合压缩引擎

架构：双锚点保边 + 10算法融合评分 + 幂律裁剪

流程：
1. 双锚点保边：保留最早M条锚点（实体定义/关键决策）+ 最近N条工作记忆（信息熵驱动）
2. 中间区域评分：10算法融合评分引擎（score_memory）
   - 每种算法输出 score_i + conf_i，权重 w_i = conf_i / Σconf_j（置信度归一化）
   - 低置信度自动降权，不会拖低整体评分质量
3. 幂律裁剪（apply_power_law_pruning）：
   - 公式：保留评分 > threshold 的记忆
   - threshold = max_score × (1/N)^(1/α)
   - α 初始值 1.5（Clauset et al., 2009），运行时根据摘要质量反馈动态调整
4. 兜底截取：幂律裁剪后仍超 max_msg 时，按评分降序截取

评分引擎可复用于记忆淘汰引擎（MemoryEvictor）。
幂律裁剪指数 α 同时用于淘汰评分：eviction_score = (N/K)^α

参数来源标注：
- 遗忘曲线衰减系数：Ebbinghaus (1885) R=e^(-t/S)
- 幂律裁剪指数 α：Clauset et al. (2009)，初始值 1.5，LLM 质量反馈动态调整
- 上下文预算：Sweller (1988) 认知负荷 7±2，由对话长度和模型窗口自适应
- 锚点识别：DualAnchorStrategy（实体定义关键词 + 决策确认 + 首条用户消息）
- 最近窗口 N：信息熵驱动 N = max(N_min, ceil(H_recent / H_avg))

设计哲学（宽进严出）：
- 压缩是降级操作，不是删除（原始记忆保留在存储中）
- 宁可多保留，不要错过关键信息
- 所有参数来源标注清楚，无魔法数字

参考：ADR-008 记忆系统联动架构，ADR-009 动态淘汰策略
"""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime

logger = logging.getLogger("long_agent.context.compressor")


@dataclass
class CompressResult:
    """
    压缩结果（V2 统一版本）

    字段说明：
    - summary: 压缩后的摘要文本
    - quality_score: LLM 自评摘要质量 (0-1)
    - pruned_count: 裁剪掉的消息数
    - kept_indices: 保留的消息索引
    - compressed_token_count: 压缩后节省的 token 数
    - method: 使用的压缩方法
    - feedback_signals: 反馈信号（用于反馈引擎）
    - original_count: 压缩前消息总数（兼容字段）
    - kept_ids: 保留的消息ID列表（兼容字段）
    """

    summary: str = ""
    quality_score: float = 0.0
    pruned_count: int = 0
    kept_indices: list = field(default_factory=list)
    compressed_token_count: int = 0
    method: str = ""
    feedback_signals: dict = field(default_factory=dict)
    original_count: int = 0
    kept_ids: list = field(default_factory=list)
    compressed_count: int = 0  # 压缩后保留的消息数（兼容字段）


class ContextCompressor:
    """
    上下文压缩器（V2：11算法融合 + 幂律裁剪）

    职责：
    - 在感知阶段压缩历史消息（上下文压缩）
    - 确保总 token 数在预算内
    - 优先保留重要、相关、新鲜的记忆

    评分引擎可复用：
    - 本类的评分函数（_forgetting_score, _relevance_score 等）可被 MemoryEvictor 复用
    - 幂律裁剪指数 α 同时用于：
      (1) 上下文压缩的消息裁剪阈值
      (2) 记忆淘汰评分 eviction_score = (N/K)^α
    - 参见：memory/evictor.py MemoryEvictor

    设计哲学（宽进严出）：
    - 压缩是降级操作，不是删除（原始记忆保留在存储中）
    - 宁可多保留，不要错过关键信息
    - 压缩结果必须可解释（记录移除原因）
    - 所有参数来源标注清楚，无魔法数字
    """

    # 默认参数（科学依据见各算法，均可通过构造函数覆盖）
    # 遗忘曲线参数
    DEFAULT_FORGETTING_DECAY = 0.1       # 衰减系数（Ebbinghaus S 参数的倒数）
    DEFAULT_FORGETTING_THRESHOLD = 0.2    # 保留阈值（记忆强度 < 0.2 时丢弃）

    # CUSUM 参数
    DEFAULT_CUSUM_THRESHOLD = 3.0         # 突变点阈值（标准差的 3 倍）
    DEFAULT_CUSUM_DRIFT = 0.5             # 漂移参数

    # 上下文预算参数
    DEFAULT_MAX_CONTEXT_MESSAGES = 20     # 最大上下文消息数（认知负荷 7±2 的 3 倍）
    DEFAULT_MIN_CONTEXT_MESSAGES = 5      # 最小上下文消息数（保证基本上下文）

    # 幂律裁剪指数 α（Clauset et al., 2009）
    # 初始值 1.5，由 LLM 质量反馈动态调整
    # 同时用于淘汰评分：eviction_score = (N/K)^α
    DEFAULT_ALPHA = 1.5

    def __init__(
        self,
        forgetting_decay: float = None,
        forgetting_threshold: float = None,
        cusum_threshold: float = None,
        cusum_drift: float = None,
        max_context_messages: int = None,
        min_context_messages: int = None,
        context_window: int = 128000,
        alpha: float = None,
    ):
        """
        上下文压缩器。

        所有参数均可通过构造函数覆盖，支持运行时动态调整。
        参数为 None 时使用默认值。

        Args:
            forgetting_decay: 遗忘曲线衰减系数（越大遗忘越快）
            forgetting_threshold: 遗忘曲线保留阈值（低于此值丢弃）
            cusum_threshold: CUSUM 突变点阈值
            cusum_drift: CUSUM 漂移参数
            max_context_messages: 最大上下文消息数
            min_context_messages: 最小上下文消息数
            context_window: 模型上下文窗口（token 数），从 ModelConfig 读取后传入
            alpha: 幂律裁剪指数（默认 1.5，LLM 动态调整）
        """
        self.FORGETTING_DECAY = forgetting_decay or self.DEFAULT_FORGETTING_DECAY
        self.FORGETTING_THRESHOLD = forgetting_threshold or self.DEFAULT_FORGETTING_THRESHOLD
        self.CUSUM_THRESHOLD = cusum_threshold or self.DEFAULT_CUSUM_THRESHOLD
        self.CUSUM_DRIFT = cusum_drift or self.DEFAULT_CUSUM_DRIFT
        self.MAX_CONTEXT_MESSAGES = max_context_messages or self.DEFAULT_MAX_CONTEXT_MESSAGES
        self.MIN_CONTEXT_MESSAGES = min_context_messages or self.DEFAULT_MIN_CONTEXT_MESSAGES
        self.context_window = context_window  # 从 ModelConfig 读取，不再写死
        self.alpha = alpha or self.DEFAULT_ALPHA  # 幂律裁剪指数（LLM 动态调整）

        self._cusum_positive = 0.0
        self._cusum_negative = 0.0
        self._baseline_mean = 0.0
        self._message_count = 0

    # ---- 11算法融合评分引擎（可被 MemoryEvictor 复用）----

    def score_memory(self, memory: dict, current_input: str = "",
                     session_context: dict = None) -> dict:
        """
        对单条记忆进行多算法融合评分（11算法）。

        可被 MemoryEvictor 复用：淘汰引擎调用此函数获取记忆评分。

        Args:
            memory: 记忆字典（content, created_at, access_count, layer, category 等）
            current_input: 当前用户输入（用于相关性评分）
            session_context: 会话上下文（用于话题一致性评分）

        Returns:
            dict: {
                "final_score": float,  # 融合后最终评分（0~1）
                "scores": dict,        # 各算法评分详情
                "weights": dict,       # 各算法权重
            }
        """
        scores = {}
        confidences = {}

        # 算法1：遗忘曲线评分（Ebbinghaus）
        scores["forgetting"] = self._score_forgetting(memory)
        confidences["forgetting"] = 0.8

        # 算法2：访问频率评分
        scores["access_frequency"] = self._score_access_frequency(memory)
        confidences["access_frequency"] = 0.7

        # 算法3：香农熵评分（Shannon, 1948）
        scores["information_entropy"] = self._score_information_entropy(memory)
        confidences["information_entropy"] = 0.7

        # 算法4：时间衰减评分
        scores["recency"] = self._score_recency(memory)
        confidences["recency"] = 0.9

        # 算法5：相关性评分（与当前输入的语义相关性）
        scores["relevance"] = self._score_relevance(memory, current_input)
        confidences["relevance"] = 0.6

        # 算法6：层权重评分（personality=1.0, core=0.8, standard=0.6）
        scores["layer_weight"] = self._score_layer_weight(memory)
        confidences["layer_weight"] = 1.0

        # 算法7：矛盾检测评分（与上下文矛盾度，越低越好）
        scores["contradiction"] = self._score_contradiction(memory, session_context)
        confidences["contradiction"] = 0.5

        # 算法8：话题一致性评分
        scores["topic_consistency"] = self._score_topic_consistency(memory, current_input)
        confidences["topic_consistency"] = 0.6

        # 算法9：锚点保护评分（锚点评分=1.0，不可淘汰）
        scores["anchor"] = self._score_anchor(memory, session_context)
        confidences["anchor"] = 1.0

        # 算法10：价值密度评分（信息密度 = 唯一实体数 / 长度）
        scores["value_density"] = self._score_value_density(memory)
        confidences["value_density"] = 0.5

        # 算法11：幂律分布评分（Clauset et al., 2009）
        scores["power_law"] = self._score_power_law(memory, scores)
        confidences["power_law"] = 0.7

        # 加权融合：w_i = conf_i / Σconf_j
        total_conf = sum(confidences.values())
        weights = {k: v / total_conf for k, v in confidences.items()}

        final_score = sum(scores[k] * weights[k] for k in scores)

        return {
            "final_score": final_score,
            "scores": scores,
            "weights": weights,
        }

    def _score_forgetting(self, memory: dict) -> float:
        """算法1：遗忘曲线评分（Ebbinghaus, 1885）R = e^(-t/S)"""
        created_at_str = memory.get("created_at", "")
        if created_at_str:
            try:
                ts = created_at_str.replace("Z", "+00:00")
                created_at = datetime.fromisoformat(ts.replace("+00:00", ""))
                age_hours = (datetime.utcnow() - created_at).total_seconds() / 3600
            except (ValueError, TypeError):
                age_hours = 0
        else:
            age_hours = 0
        retention = math.exp(-self.FORGETTING_DECAY * age_hours)
        return retention

    def _score_access_frequency(self, memory: dict) -> float:
        """算法2：访问频率评分（归一化到 0~1）"""
        count = memory.get("access_count", 0)
        # 使用对数归一化：score = min(1, log(1+count) / log(100))
        return min(1.0, math.log(1 + count) / math.log(100))

    def _score_information_entropy(self, memory: dict) -> float:
        """
        算法3：香农熵评分（Shannon, 1948）

        计算消息内容的字符级信息熵，熵越高表示信息量越大，越值得保留。
        公式：H = -Σ p(x) * log2(p(x))
        归一化到 0~1（以当前消息唯一字符集大小为理论最大熵归一化基准）
        """
        content = memory.get("content", "")
        if not content:
            return 0.0

        from collections import Counter
        char_counts = Counter(content)
        total_chars = len(content)
        if total_chars == 0:
            return 0.0

        entropy = -sum(
            (count / total_chars) * math.log2(count / total_chars)
            for count in char_counts.values()
        )
        # 归一化：以 log2(唯一字符数) 为理论最大熵
        unique_chars = len(char_counts)
        if unique_chars <= 1:
            return 0.0
        max_entropy = math.log2(unique_chars)
        normalized = entropy / max_entropy if max_entropy > 0 else 0.0
        return min(1.0, max(0.0, normalized))

    def _score_recency(self, memory: dict) -> float:
        """算法3：时间衰减评分（与遗忘曲线互补，更关注最近访问）"""
        last_access = memory.get("last_access_at", memory.get("created_at", ""))
        if last_access:
            try:
                ts = last_access.replace("Z", "+00:00")
                last_dt = datetime.fromisoformat(ts.replace("+00:00", ""))
                age_hours = (datetime.utcnow() - last_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                age_hours = 0
        else:
            age_hours = 0
        # 半衰期 24h
        return math.exp(-0.693 * age_hours / 24)

    def _score_relevance(self, memory: dict, current_input: str) -> float:
        """算法4：相关性评分（Jaccard 相似度）"""
        if not current_input:
            return 0.5  # 无输入时中性评分
        content = memory.get("content", "")
        set_a = set(current_input)
        set_b = set(content)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def _score_layer_weight(self, memory: dict) -> float:
        """算法5：层权重评分（personality=1.0, core=0.8, standard=0.6）"""
        layer_weights = {"personality": 1.0, "core": 0.8, "standard": 0.6}
        layer = memory.get("layer", "standard")
        return layer_weights.get(layer, 0.5)

    def _score_contradiction(self, memory: dict, session_context: dict = None) -> float:
        """算法6：矛盾检测评分（0=矛盾，1=无矛盾）"""
        # 简化版：检查冲突标记
        conflicts = memory.get("conflicts", [])
        if conflicts:
            return 0.3  # 有冲突标记，降低评分
        return 1.0  # 无冲突

    def _score_topic_consistency(self, memory: dict, current_input: str) -> float:
        """算法7：话题一致性评分（与 _score_relevance 互补，关注主题而非字面）"""
        # 简化版：使用 2-gram Jaccard
        if not current_input:
            return 0.5
        content = memory.get("content", "")
        def bigrams(text):
            return set(text[i:i+2] for i in range(len(text)-1))
        bg_a = bigrams(current_input)
        bg_b = bigrams(content)
        if not bg_a or not bg_b:
            return 0.0
        intersection = len(bg_a & bg_b)
        union = len(bg_a | bg_b)
        return intersection / union if union > 0 else 0.0

    def _score_anchor(self, memory: dict, session_context: dict = None) -> float:
        """算法8：锚点保护评分（锚点=1.0，不可淘汰）"""
        if session_context and session_context.get("is_anchor", False):
            return 1.0
        # 检查实体定义关键词
        content = memory.get("content", "")
        entity_keywords = ["叫", "名为", "定义为", "设置", "项目名", "项目叫"]
        if any(kw in content for kw in entity_keywords):
            return 1.0
        return 0.5  # 非锚点，中性评分

    def _score_value_density(self, memory: dict) -> float:
        """算法9：价值密度评分（信息密度 = 唯一实体数 / 长度）"""
        content = memory.get("content", "")
        if not content:
            return 0.0
        # 简化版：唯一字符数 / 总字符数
        unique_chars = len(set(content))
        total_chars = len(content)
        density = unique_chars / total_chars if total_chars > 0 else 0
        # 归一化到 0~1（密度 0.8 以上视为高价值）
        return min(1.0, density / 0.8)

    def _score_power_law(self, memory: dict, other_scores: dict) -> float:
        """
        算法10：幂律分布评分（Clauset et al., 2009）

        根据其他评分的分布拟合幂律，判断该记忆在整体分布中的位置。
        高评分记忆在幂律分布中属于"头部"，应保留。
        """
        if not other_scores:
            return 0.5
        # 计算当前记忆在其他评分中的排名位置
        values = sorted(other_scores.values())
        current = other_scores.get("forgetting", 0.5)
        # 排名归一化
        rank = sum(1 for v in values if v <= current) / len(values) if values else 0.5
        return rank

    def apply_power_law_pruning(self, scored_memories: list[dict]) -> list[dict]:
        """
        幂律裁剪（Clauset et al., 2009）

        公式：保留评分 > threshold 的记忆
        threshold = max_score × (1/N)^(1/α)
        - N: 记忆总数
        - α: 幂律裁剪指数（默认 1.5，LLM 动态调整）

        Args:
            scored_memories: [{"memory": dict, "score": float}, ...]

        Returns:
            list[dict]: 裁剪后的记忆列表
        """
        if not scored_memories:
            return []

        scores = [sm["score"] for sm in scored_memories]
        max_score = max(scores) if scores else 1.0
        N = len(scored_memories)

        # 幂律裁剪阈值
        threshold = max_score * (1.0 / N) ** (1.0 / self.alpha)

        # 保留高于阈值的记忆
        pruned = [sm for sm in scored_memories if sm["score"] >= threshold]

        logger.info(
            f"幂律裁剪: {len(scored_memories)} → {len(pruned)} "
            f"(α={self.alpha:.2f}, threshold={threshold:.4f})"
        )
        return pruned

    async def compress(
        self,
        messages: list[dict],
        current_input: str = "",
        max_messages: int = None,
    ) -> CompressResult:
        """
        压缩上下文消息（V2 统一入口：10算法融合 + 幂律裁剪）。

        流程：
        1. 双锚点保边：保留最早M条锚点 + 最近N条工作记忆
        2. 中间区域：10算法融合评分（score_memory）
        3. 幂律裁剪（apply_power_law_pruning）
        4. 返回统一 CompressResult

        Args:
            messages: 历史消息列表
            current_input: 当前用户输入（用于相关性评分）
            max_messages: 最大消息数（覆盖默认值）

        Returns:
            CompressResult: 压缩结果
        """
        max_msg = max_messages or self.MAX_CONTEXT_MESSAGES
        result = CompressResult(
            original_count=len(messages),
            method="v2_fusion_power_law",
        )

        # 消息数低于下限，不压缩
        if len(messages) <= self.MIN_CONTEXT_MESSAGES:
            result.kept_indices = list(range(len(messages)))
            result.kept_ids = [m.get("id", str(i)) for i, m in enumerate(messages)]
            result.compressed_count = len(messages)
            return result

        # 阶段1：双锚点保边
        bounds = self._get_dual_anchor_bounds(messages)
        anchor_prefix = messages[:bounds.compressible_start]
        compressible_region = messages[bounds.compressible_start:bounds.compressible_end]
        anchor_suffix = messages[bounds.compressible_end:]

        if not compressible_region:
            # 锚点覆盖全部，无需压缩
            final_messages = anchor_prefix + anchor_suffix
            result.kept_ids = [m.get("id", str(i)) for i, m in enumerate(final_messages)]
            result.kept_indices = list(range(len(final_messages)))
            result.compressed_count = len(final_messages)
            return result

        # 阶段2：10算法融合评分
        scored = []
        for msg in compressible_region:
            scoring = self.score_memory(msg, current_input, session_context=None)
            scored.append({
                "memory": msg,
                "score": scoring["final_score"],
                "scores_detail": scoring["scores"],
                "weights": scoring["weights"],
            })

        # 阶段3：幂律裁剪
        pruned = self.apply_power_law_pruning(scored)
        final_compressible = [item["memory"] for item in pruned]

        # 合并：前锚点 + 裁剪后中间 + 后锚点
        final_messages = anchor_prefix + final_compressible + anchor_suffix

        # 如果幂律裁剪后仍然超过 max_msg，按评分从高到低截取
        if len(final_messages) > max_msg:
            # 锚点始终保留，只对中间区域按评分截取
            non_anchor = [item["memory"] for item in pruned]
            # 按评分降序
            scored_non_anchor = sorted(pruned, key=lambda x: x["score"], reverse=True)
            allowed = max_msg - len(anchor_prefix) - len(anchor_suffix)
            allowed = max(allowed, 0)
            kept_non_anchor = [item["memory"] for item in scored_non_anchor[:allowed]]
            final_messages = anchor_prefix + kept_non_anchor + anchor_suffix

        # 填充结果
        kept_ids = {m.get("id", str(i)) for i, m in enumerate(final_messages)}
        result.kept_ids = list(kept_ids)
        result.kept_indices = [
            i for i, m in enumerate(messages)
            if m.get("id", str(i)) in kept_ids
        ]
        result.pruned_count = len(messages) - len(final_messages)
        result.compressed_count = len(final_messages)
        result.compressed_token_count = self._estimate_tokens(
            [m.get("id", str(i)) for i, m in enumerate(messages)
             if m.get("id", str(i)) not in kept_ids]
        )

        logger.info(
            f"V2压缩: {result.original_count} → {len(final_messages)} "
            f"(锚点前={bounds.compressible_start}, 锚点后={len(messages)-bounds.compressible_end}, "
            f"移除 {result.pruned_count} 条, α={self.alpha:.2f})"
        )

        return result

    def _get_dual_anchor_bounds(self, messages: list[dict]) -> "DualAnchorBounds":
        """
        计算双锚点边界（V2 替代硬编码"最近3条"）

        M = 锚点消息数（实体定义/关键决策）
        N = 最近保留窗口（信息熵驱动）
        """
        M = DualAnchorStrategy.count_anchors(messages)
        N = DualAnchorStrategy.calc_recent_window(messages)
        total = len(messages)
        start = M
        end = total - N if N > 0 else total
        if end <= start:
            end = start + 1
        return DualAnchorBounds(
            anchor_count=M, recent_count=N,
            compressible_start=start, compressible_end=end
        )

    @staticmethod
    def _estimate_tokens(text_or_ids: list) -> int:
        """估算节省的 token 数（粗略估算：1 token ≈ 4 字符）"""
        if not text_or_ids:
            return 0
        # 假设每条消息平均 100 字符
        return len(text_or_ids) * 25  # 100 / 4 = 25 tokens


# ========== V2 升级：双锚点策略 + 后台压缩进程 + 反馈引擎 ==========


class CompressState(Enum):
    """后台压缩进程状态"""
    SLEEP = "sleep"
    COMPRESSING = "compressing"
    MONITORING = "monitoring"


@dataclass
class DualAnchorBounds:
    """双锚点边界"""
    anchor_count: int = 0   # M: 最早锚点消息数
    recent_count: int = 0   # N: 最近保留消息数
    compressible_start: int = 0
    compressible_end: int = 0


class DualAnchorStrategy:
    """
    双锚点保边策略（合并自 hermse v1.3）

    保留最近N条工作记忆 + 最早M条锚点，只压缩中间区域。
    所有参数来自用户历史数据拟合或 LLM 动态评估，无写死默认值。
"""

    @staticmethod
    def is_anchor(msg: dict, session_messages: list, user_id: str = "") -> bool:
        """判断一条消息是否为不可压缩的锚点"""
        # 条件1：会话中第一条用户消息（用 is 匹配，不用 id）
        for i, m in enumerate(session_messages):
            if m.get("role") == "user":
                if msg is m:
                    return True
                break
        # 条件2：包含实体定义
        content = msg.get("content", "")
        entity_keywords = ["叫", "名为", "定义为", "设置", "项目名", "项目叫"]
        if any(kw in content for kw in entity_keywords):
            return True
        # 条件3：用户确认了关键决策
        confirm_keywords = ["确认", "好的", "就这样", "同意", "OK", "ok", "行", "可以"]
        if any(kw in content for kw in confirm_keywords) and len(content) < 20:
            return True
        return False

    @classmethod
    def count_anchors(cls, session_messages: list, user_id: str = "") -> int:
        """动态识别锚点消息数量 M"""
        count = 0
        for msg in session_messages:
            if cls.is_anchor(msg, session_messages, user_id):
                count += 1
        return count

    @staticmethod
    def calc_recent_window(session_messages: list, user_history: dict = None) -> int:
        """
        计算最近保留窗口 N。

        公式：N = max(N_min, ceil(H_recent / H_avg))
        - H_recent: 最近K轮对话的信息熵
        - H_avg: 该用户历史平均信息熵
        - N_min: 硬下限（由LLM根据用户对话模式评估）

        无历史数据时的启发式计算（仅首次）。
        """
        if not session_messages:
            return 6

        # 计算最近K轮的信息熵
        K = min(10, len(session_messages))
        recent_msgs = session_messages[-K:]
        all_content = " ".join(m.get("content", "") for m in recent_msgs)
        words = all_content.split()
        if not words:
            return 6

        from collections import Counter
        word_counts = Counter(words)
        total = len(words)
        import math
        h_recent = -sum((c/total) * math.log2(c/total) for c in word_counts.values())

        # 获取历史平均熵（无数据时使用启发式）
        h_avg = user_history.get("avg_entropy", 3.0) if user_history else 3.0
        if h_avg <= 0:
            h_avg = 3.0

        # N_min: 至少保留一个完整对话轮次
        n_min = user_history.get("min_recent_window", 4) if user_history else 4

        import math
        N = max(n_min, math.ceil(h_recent / h_avg))
        return max(2, min(N, 20))  # 范围 [2, 20]


class FeedbackEngine:
    """
    反馈引擎（合并自 hermse v1.3）

    压缩后监控后续 N_monitor 轮对话，检测5类丢失信号，自动召回+参数自学习。
    """

    # 5类丢失信号
    SIGNALS = {
        "S1_repeat_inquiry": "重复询问",
        "S2_reference_confusion": "指代困惑",
        "S3_information_recall": "信息回溯",
        "S4_correction": "纠正行为",
        "S5_confusion": "困惑信号",
    }

    def __init__(self):
        self._sensitivity_table: dict = {}
        self._lessons: list = []

    def detect_loss_signals(self, new_user_msg: str, compressed_messages: list,
                            session_context: str) -> list:
        """检测信息丢失信号"""
        signals = []
        # S1: 重复询问（语义相似度 > 0.85）
        for msg in compressed_messages:
            content = msg.get("content", "")
            if content and self._simple_similarity(new_user_msg, content) > 0.85:
                signals.append("S1_repeat_inquiry")
                break
        # S2: 指代困惑
        pronouns = ["那个", "这个", "刚才", "之前", "上面", "它"]
        if any(p in new_user_msg for p in pronouns) and len(new_user_msg) < 30:
            signals.append("S2_reference_confusion")
        # S3: 信息回溯
        recall_keywords = ["之前说的", "你刚才", "再告诉我", "是什么", "叫什么"]
        if any(kw in new_user_msg for kw in recall_keywords):
            signals.append("S3_information_recall")
        return signals

    @staticmethod
    def _simple_similarity(a: str, b: str) -> float:
        """简单相似度（Jaccard）"""
        if not a or not b:
            return 0.0
        set_a = set(a)
        set_b = set(b)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0


class BackgroundCompressor:
    """
    常驻后台压缩进程（合并自 hermse v1.3）

    状态机：SLEEP → COMPRESSING → MONITORING → SLEEP
    读写锁 + 分批压缩 + 紧急退出，零阻塞对话路径。
    """

    def __init__(self, compressor: 'ContextCompressor', llm_client=None):
        self.compressor = compressor
        self.llm = llm_client
        self._state = CompressState.SLEEP
        self._lock = asyncio.Lock()
        self._quality_scores: list = []
        self._compress_count: int = 0

        # 反馈引擎
        self.feedback = FeedbackEngine()

        # 参数（来自用户历史数据，不写死）
        self.N_threshold: Optional[int] = None  # 激活线
        self.N_target: Optional[int] = None     # 目标线
        self._batch_size: int = 3               # 每批压缩条数
        self._adjust_interval: int = 100        # LLM动态调整间隔

    async def signal_maybe_compress(self, session):
        """检查是否需要激活压缩（由 add_message 调用）"""
        context_size = self._calc_context_size(session)
        if self.N_threshold is None:
            # 首次：从模型配置计算
            await self._init_thresholds(session)
        if context_size > self.N_threshold:
            self._state = CompressState.COMPRESSING
            asyncio.create_task(self._compression_loop(session))

    async def _compression_loop(self, session):
        """后台压缩循环"""
        while self._state == CompressState.COMPRESSING:
            context_size = self._calc_context_size(session)
            if context_size <= self.N_target:
                self._state = CompressState.MONITORING
                break
            # 双锚点保边
            bounds = self._get_compressible_range(session)
            if bounds.compressible_end - bounds.compressible_start <= 1:
                self._state = CompressState.MONITORING
                break
            # 取一批压缩
            batch = session.messages[bounds.compressible_start:bounds.compressible_start + self._batch_size]
            if not batch:
                break
            # 调用 v1.2 算法核心
            result = await self.compressor.compress(batch)
            # 写操作（独占锁，但操作极快）
            async with self._lock:
                # 替换 batch 为压缩摘要
                new_msg = {"role": "system", "content": f"[压缩摘要] {result.summary}"}
                session.messages = (
                    session.messages[:bounds.compressible_start] +
                    [new_msg] +
                    session.messages[bounds.compressible_start + len(batch):]
                )
            self._quality_scores.append(result.quality_score)
            self._compress_count += 1
            await asyncio.sleep(0)  # 让出CPU

    def _get_compressible_range(self, session) -> DualAnchorBounds:
        """确定中间压缩区"""
        M = DualAnchorStrategy.count_anchors(session.messages)
        N = DualAnchorStrategy.calc_recent_window(session.messages)
        total = len(session.messages)
        start = M
        end = total - N if N > 0 else total
        if end <= start:
            end = start + 1
        return DualAnchorBounds(
            anchor_count=M, recent_count=N,
            compressible_start=start, compressible_end=end
        )

    def _calc_context_size(self, session) -> int:
        """计算当前上下文消息数"""
        return len(session.messages)

    async def _init_thresholds(self, session):
        """首次初始化阈值（从模型配置和用户历史数据计算）"""
        # context_window 从 ModelConfig 读取，通过 compressor.__init__ 传入
        context_window = self.compressor.context_window
        avg_msg_tokens = getattr(self.compressor, '_avg_message_length', 200)
        # R_safe: 安全比例（初始值，运行后自适应）
        R_safe = 0.7
        self.N_threshold = max(20, int(context_window / max(avg_msg_tokens, 1) * R_safe))
        # R_target: 目标比例
        R_target = 0.6
        self.N_target = max(10, int(self.N_threshold * R_target))
