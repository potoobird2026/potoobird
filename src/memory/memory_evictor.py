"""
MemoryEvictor — 记忆淘汰引擎

职责：
- 当记忆数量接近容量上限时，淘汰低价值记忆
- 复用 ContextCompressor 的 10 算法评分引擎
- 使用幂律裁剪（Clauset et al., 2009）决定淘汰哪些记忆

淘汰策略（宽进严出）：
1. 写入不过滤（由 LogisticGrowth 的 get_write_probability=1.0 保证）
2. 淘汰触发：eviction_score = (N/K)^α > threshold
3. 淘汰选择：10算法融合评分最低的记忆先淘汰
4. 锚点保护：锚点记忆（personality层、实体定义）不可淘汰

参数来源：
- α = 1.5：幂律裁剪指数（Clauset et al., 2009），LLM 动态调整
- threshold = 0.85：淘汰触发阈值（对应 N/K ≈ 0.9 时 α=1.5 的评分）
- K = 10000：SQLite + FTS5 实测经验值

设计哲学：
- 淘汰是"降级"不是"删除"：被淘汰的记忆标记为 evicted，不物理删除
- 锚点不可淘汰：人格层、实体定义等关键记忆永久保留
- 所有参数来源标注清楚，无魔法数字

参考：ADR-008 记忆系统联动架构，ADR-009 动态淘汰策略
"""

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger("long_agent.memory.evictor")


@dataclass
class EvictionResult:
    """淘汰结果"""

    evicted_count: int = 0  # 淘汰的记忆数量
    evicted_ids: list = field(default_factory=list)  # 被淘汰的记忆 ID
    protected_count: int = 0  # 被保护的锚点数量
    remaining_count: int = 0  # 剩余记忆数量
    eviction_score: float = 0.0  # 触发时的淘汰评分


class MemoryEvictor:
    """
    记忆淘汰引擎。

    职责：
    - 复用 ContextCompressor 的 10 算法评分引擎对记忆评分
    - 使用幂律裁剪决定淘汰哪些记忆
    - 保护锚点记忆不被淘汰

    淘汰流程：
    1. 计算 eviction_score = (N/K)^α
    2. 若 eviction_score > threshold，触发淘汰
    3. 对所有记忆调用 compressor.score_memory() 评分
    4. 按评分升序排列，从最低分开始淘汰
    5. 锚点记忆（is_anchor=True, layer=personality）跳过
    6. 直到 eviction_score <= threshold 或无可淘汰记忆
    """

    # 幂律裁剪指数 α（Clauset et al., 2009）
    # 初始值 1.5，由 LLM 动态调整
    DEFAULT_ALPHA = 1.5

    # 淘汰触发阈值
    # 来源：对应 N/K ≈ 0.9 时 α=1.5 的 eviction_score ≈ 0.85
    DEFAULT_THRESHOLD = 0.85

    # 目标 eviction_score（淘汰到此值以下停止）
    TARGET_SCORE = 0.70

    def __init__(self, compressor=None, alpha: float = None, threshold: float = None):
        """
        Args:
            compressor: ContextCompressor 实例（用于 score_memory 评分）
            alpha: 幂律裁剪指数（默认 1.5，LLM 动态调整）
            threshold: 淘汰触发阈值（默认 0.85）
        """
        self.compressor = compressor
        self.alpha = alpha or self.DEFAULT_ALPHA
        self.threshold = threshold or self.DEFAULT_THRESHOLD

    def evict(
        self,
        memories: list[dict],
        current_count: int,
        capacity_k: int,
        current_input: str = "",
    ) -> EvictionResult:
        """
        执行记忆淘汰。

        流程：
        1. 计算 eviction_score = (N/K)^α
        2. 若 eviction_score <= threshold，不淘汰
        3. 若 eviction_score > threshold，触发淘汰
        4. 评分所有记忆（复用 compressor.score_memory）
        5. 从最低分开始淘汰（跳过锚点）
        6. 直到 eviction_score <= TARGET_SCORE

        Args:
            memories: 所有记忆列表
            current_count: 当前记忆数量 N
            capacity_k: 容量上限 K
            current_input: 当前用户输入（用于相关性评分）

        Returns:
            EvictionResult: 淘汰结果
        """
        result = EvictionResult()

        # 计算当前淘汰评分
        eviction_score = self._calc_eviction_score(current_count, capacity_k)
        result.eviction_score = eviction_score

        # 未触发淘汰
        if eviction_score <= self.threshold:
            result.remaining_count = current_count
            return result

        logger.info(
            f"淘汰触发: eviction_score={eviction_score:.4f} > threshold={self.threshold}, "
            f"N={current_count}, K={capacity_k}"
        )

        # 评分所有记忆
        scored = self._score_all_memories(memories, current_input)

        # 按评分升序排列（低分先淘汰）
        scored.sort(key=lambda x: x["score"])

        # 淘汰低分记忆（跳过锚点）
        evicted_ids = []
        protected_count = 0
        remaining = list(memories)

        for item in scored:
            mem = item["memory"]
            mem_id = mem.get("id", id(mem))

            # 锚点保护
            if self._is_anchor(mem):
                protected_count += 1
                continue

            # 检查是否已经达到目标
            new_count = current_count - len(evicted_ids)
            new_score = self._calc_eviction_score(new_count, capacity_k)
            if new_score <= self.TARGET_SCORE:
                break

            # 淘汰
            evicted_ids.append(mem_id)
            remaining = [m for m in remaining if m.get("id", id(m)) != mem_id]

        result.evicted_count = len(evicted_ids)
        result.evicted_ids = evicted_ids
        result.protected_count = protected_count
        result.remaining_count = len(remaining)

        logger.info(
            f"淘汰完成: 淘汰 {result.evicted_count} 条, "
            f"保护 {result.protected_count} 条锚点, "
            f"剩余 {result.remaining_count} 条"
        )
        return result

    def _calc_eviction_score(self, current_count: int, capacity_k: int) -> float:
        """
        计算淘汰评分。

        公式：eviction_score = (N / K) ^ α
        - N / K：当前记忆密度（0~1）
        - α：幂律裁剪指数（默认 1.5）
        - α > 1 时，N 越接近 K，淘汰压力越大（非线性加速）

        Returns:
            float: 淘汰评分（0~1）
        """
        if capacity_k <= 0:
            return 1.0
        ratio = current_count / capacity_k
        return ratio**self.alpha

    def _score_all_memories(
        self,
        memories: list[dict],
        current_input: str,
    ) -> list[dict]:
        """
        对所有记忆评分（复用 ContextCompressor.score_memory）。

        若 compressor 未注入，使用简化版评分。

        Returns:
            list[dict]: [{"memory": dict, "score": float}, ...]
        """
        scored = []

        for mem in memories:
            if self.compressor is not None:
                # 复用 ContextCompressor 的 10 算法融合评分
                score_result = self.compressor.score_memory(
                    memory=mem,
                    current_input=current_input,
                )
                score = score_result["final_score"]
            else:
                # 简化版评分（无 compressor 时使用）
                score = self._simple_score(mem, current_input)

            scored.append({"memory": mem, "score": score})

        return scored

    def _simple_score(self, memory: dict, current_input: str) -> float:
        """
        简化版评分（无 compressor 时使用）。

        使用 3 个简单指标：
        1. 访问频率（40%）
        2. 时间衰减（30%）
        3. 层权重（30%）
        """
        # 访问频率
        access_count = memory.get("access_count", 0)
        freq_score = min(1.0, math.log(1 + access_count) / math.log(100))

        # 时间衰减
        import time

        last_access = memory.get("last_access_at", memory.get("created_at", ""))
        if last_access:
            try:
                age_hours = (time.time() - float(last_access)) / 3600
            except (ValueError, TypeError):
                age_hours = 0
        else:
            age_hours = 0
        recency_score = math.exp(-0.693 * age_hours / 24)

        # 层权重
        layer_weights = {"personality": 1.0, "core": 0.8, "standard": 0.6}
        layer = memory.get("layer", "standard")
        layer_score = layer_weights.get(layer, 0.5)

        return 0.4 * freq_score + 0.3 * recency_score + 0.3 * layer_score

    def _is_anchor(self, memory: dict) -> bool:
        """
        判断是否为锚点记忆（不可淘汰）。

        锚点条件：
        1. layer == "personality"（人格层，永久保留）
        2. is_anchor 标记为 True
        3. 包含实体定义关键词

        Returns:
            bool: 是否为锚点
        """
        if memory.get("layer") == "personality":
            return True
        if memory.get("is_anchor", False):
            return True
        content = memory.get("content", "")
        anchor_keywords = ["叫", "名为", "定义为", "设置", "项目名", "项目叫"]
        if any(kw in content for kw in anchor_keywords):
            return True
        return False
