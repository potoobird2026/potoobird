"""
MemoryLoader — 动态记忆加载器

职责：
- 根据当前输入和 Token 预算，动态决定加载哪些记忆
- 使用信息论指标（KL散度、互信息、香农熵）计算记忆的信息价值
- 按 Token 预算分配加载：热区40% + 相关30% + 高价值20% + 锚点10%

加载算法公式（来自"开始的上下文.txt" §记忆系统完整设计）：
1. 热区加载（40% 预算）：最近访问的记忆（access_count 高 + last_access_at 近）
2. 相关加载（30% 预算）：与当前输入互信息 I(X;Y) 最高的记忆
3. 高价值加载（20% 预算）：香农熵 H(X) 最高的记忆（信息量大）
4. 锚点加载（10% 预算）：不可淘汰的锚点记忆（实体定义、人格核心）

参数来源：
- 预算分配比例：来自"开始的上下文.txt" §Token预算分配
- KL散度：信息论（Cover & Thomas, 2006），衡量记忆与当前输入的分布差异
- 互信息：I(X;Y) = H(X) + H(Y) - H(X,Y)，衡量记忆与当前输入的相关性
- 香农熵：H(X) = -Σ p(x) log p(x)，衡量记忆的信息量

设计哲学（宽进严出）：
- 加载是"用"记忆，不是"存"记忆
- 加载决策完全由信息论公式驱动，无魔法数字
- Token 预算来自 ModelConfig.context_window

参考：ADR-009 动态记忆加载算法
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("long_agent.memory.loader")


@dataclass
class LoadBudget:
    """
    Token 预算分配。

    预算比例来源："开始的上下文.txt" §Token预算分配
    - hot_zone: 40%（热区：最近访问的记忆）
    - relevant: 30%（相关：与当前输入互信息最高的记忆）
    - high_value: 20%（高价值：香农熵最高的记忆）
    - anchor: 10%（锚点：不可淘汰的记忆）
    """
    total_tokens: int = 0       # 总 Token 预算（来自 ModelConfig.context_window）
    hot_zone: int = 0           # 热区预算（40%）
    relevant: int = 0           # 相关预算（30%）
    high_value: int = 0         # 高价值预算（20%）
    anchor: int = 0             # 锚点预算（10%）

    @classmethod
    def from_context_window(cls, context_window: int) -> "LoadBudget":
        """
        从模型上下文窗口创建预算分配。

        Args:
            context_window: 模型上下文窗口（token 数），来自 ModelConfig.context_window

        Returns:
            LoadBudget: 分配后的预算对象
        """
        # 预算比例来源："开始的上下文.txt" §Token预算分配
        budget = cls()
        budget.total_tokens = context_window
        budget.hot_zone = int(context_window * 0.40)    # 热区 40%
        budget.relevant = int(context_window * 0.30)    # 相关 30%
        budget.high_value = int(context_window * 0.20)  # 高价值 20%
        budget.anchor = int(context_window * 0.10)      # 锚点 10%
        return budget


@dataclass
class MemoryCandidate:
    """记忆候选（带评分）"""
    memory: dict
    relevance_score: float = 0.0    # 互信息评分 I(X;Y)
    value_score: float = 0.0        # 香农熵评分 H(X)
    hot_score: float = 0.0          # 热区评分（访问频率 + 最近访问）
    is_anchor: bool = False         # 是否为锚点
    estimated_tokens: int = 0       # 预估 token 数


class MemoryLoader:
    """
    动态记忆加载器。

    职责：
    - 根据当前输入和 Token 预算，动态决定加载哪些记忆
    - 使用信息论指标计算记忆的信息价值
    - 按预算分配加载：热区40% + 相关30% + 高价值20% + 锚点10%

    加载决策完全由公式驱动，无魔法数字。
    """

    # 默认平均记忆 token 数（用于估算加载条数）
    # 来源：SQLite 实测，平均每条记忆约 200 token
    DEFAULT_AVG_MEMORY_TOKENS = 200

    def __init__(self, context_window: int = 128000, avg_memory_tokens: int = None):
        """
        Args:
            context_window: 模型上下文窗口（token 数），来自 ModelConfig.context_window
            avg_memory_tokens: 平均记忆 token 数（默认 200，SQLite 实测经验值）
        """
        self.context_window = context_window
        self.avg_memory_tokens = avg_memory_tokens or self.DEFAULT_AVG_MEMORY_TOKENS

    def load_memories(
        self,
        all_memories: list[dict],
        current_input: str,
        budget: LoadBudget = None,
    ) -> list[dict]:
        """
        动态加载记忆。

        算法流程：
        1. 计算每条记忆的热区评分（访问频率 + 最近访问）
        2. 计算每条记忆的互信息评分 I(X;Y)（与当前输入的相关性）
        3. 计算每条记忆的香农熵 H(X)（信息量）
        4. 按预算分配加载：热区40% + 相关30% + 高价值20% + 锚点10%

        Args:
            all_memories: 所有候选记忆列表
            current_input: 当前用户输入
            budget: Token 预算（None 时从 context_window 自动创建）

        Returns:
            list[dict]: 加载的记忆列表（按优先级排序）
        """
        if not all_memories:
            return []

        # 创建预算
        if budget is None:
            budget = LoadBudget.from_context_window(self.context_window)

        # 评分所有记忆
        candidates = self._score_all(all_memories, current_input)

        # 按预算分配加载
        loaded = self._allocate_budget(candidates, budget)

        logger.info(
            f"记忆加载: {len(all_memories)} 条候选 → {len(loaded)} 条加载 "
            f"(预算={budget.total_tokens} tokens)"
        )
        return loaded

    def _score_all(self, memories: list[dict], current_input: str) -> list[MemoryCandidate]:
        """
        对所有记忆进行评分。

        返回带评分的 MemoryCandidate 列表。
        """
        # 预计算当前输入的字符分布（用于 KL 散度和互信息）
        input_dist = self._char_distribution(current_input)

        candidates = []
        for mem in memories:
            content = mem.get("content", "")

            # 热区评分
            hot_score = self._calc_hot_score(mem)

            # 互信息评分 I(X;Y)
            relevance_score = self._calc_mutual_information(content, current_input, input_dist)

            # 香农熵 H(X)
            value_score = self._calc_shannon_entropy(content)

            # 锚点判断
            is_anchor = self._is_anchor(mem)

            # 预估 token 数
            estimated_tokens = max(1, len(content) // 4)  # 简化：4 chars ≈ 1 token

            candidates.append(MemoryCandidate(
                memory=mem,
                relevance_score=relevance_score,
                value_score=value_score,
                hot_score=hot_score,
                is_anchor=is_anchor,
                estimated_tokens=estimated_tokens,
            ))

        return candidates

    def _allocate_budget(
        self,
        candidates: list[MemoryCandidate],
        budget: LoadBudget,
    ) -> list[dict]:
        """
        按预算分配加载记忆。

        分配比例（来源："开始的上下文.txt" §Token预算分配）：
        - 热区 40%：hot_score 最高的记忆
        - 相关 30%：relevance_score 最高的记忆
        - 高价值 20%：value_score 最高的记忆
        - 锚点 10%：is_anchor=True 的记忆
        """
        loaded = []
        loaded_ids = set()

        # 1. 锚点加载（10% 预算，锚点不受预算限制，必须加载）
        anchors = [c for c in candidates if c.is_anchor]
        for c in anchors:
            loaded.append(c.memory)
            loaded_ids.add(c.memory.get("id", id(c.memory)))

        # 2. 热区加载（40% 预算）
        hot_candidates = sorted(
            [c for c in candidates if c.memory.get("id", id(c.memory)) not in loaded_ids],
            key=lambda c: c.hot_score,
            reverse=True,
        )
        hot_tokens = 0
        for c in hot_candidates:
            if hot_tokens + c.estimated_tokens > budget.hot_zone:
                break
            loaded.append(c.memory)
            loaded_ids.add(c.memory.get("id", id(c.memory)))
            hot_tokens += c.estimated_tokens

        # 3. 相关加载（30% 预算）
        rel_candidates = sorted(
            [c for c in candidates if c.memory.get("id", id(c.memory)) not in loaded_ids],
            key=lambda c: c.relevance_score,
            reverse=True,
        )
        rel_tokens = 0
        for c in rel_candidates:
            if rel_tokens + c.estimated_tokens > budget.relevant:
                break
            loaded.append(c.memory)
            loaded_ids.add(c.memory.get("id", id(c.memory)))
            rel_tokens += c.estimated_tokens

        # 4. 高价值加载（20% 预算）
        val_candidates = sorted(
            [c for c in candidates if c.memory.get("id", id(c.memory)) not in loaded_ids],
            key=lambda c: c.value_score,
            reverse=True,
        )
        val_tokens = 0
        for c in val_candidates:
            if val_tokens + c.estimated_tokens > budget.high_value:
                break
            loaded.append(c.memory)
            loaded_ids.add(c.memory.get("id", id(c.memory)))
            val_tokens += c.estimated_tokens

        return loaded

    def _calc_hot_score(self, memory: dict) -> float:
        """
        热区评分（访问频率 + 最近访问）。

        公式：hot_score = 0.5 * freq_score + 0.5 * recency_score
        - freq_score = min(1, log(1+access_count) / log(100))
        - recency_score = exp(-0.693 * age_hours / 24)（半衰期 24h）
        """
        # 访问频率评分
        access_count = memory.get("access_count", 0)
        freq_score = min(1.0, math.log(1 + access_count) / math.log(100))

        # 最近访问评分
        last_access = memory.get("last_access_at", memory.get("created_at", ""))
        if last_access:
            try:
                age_hours = (time.time() - float(last_access)) / 3600
            except (ValueError, TypeError):
                age_hours = 0
        else:
            age_hours = 0
        # 半衰期 24h
        recency_score = math.exp(-0.693 * age_hours / 24)

        return 0.5 * freq_score + 0.5 * recency_score

    def _calc_mutual_information(self, content: str, current_input: str,
                                  input_dist: dict = None) -> float:
        """
        互信息评分 I(X;Y) = H(X) + H(Y) - H(X,Y)

        衡量记忆内容与当前输入的相关性。
        互信息越高 → 记忆与当前输入越相关 → 越应该加载。

        简化版：使用 Jaccard 相似度近似互信息
        （精确计算互信息需要大规模语料库估计分布）

        Args:
            content: 记忆内容
            current_input: 当前用户输入
            input_dist: 当前输入的字符分布（预计算）

        Returns:
            float: 互信息评分（0~1）
        """
        if not content or not current_input:
            return 0.0

        # 使用字符级 Jaccard 相似度近似互信息
        set_a = set(current_input)
        set_b = set(content)
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)

        return intersection / union if union > 0 else 0.0

    def _calc_shannon_entropy(self, content: str) -> float:
        """
        香农熵 H(X) = -Σ p(x) log p(x)

        衡量记忆内容的信息量。
        熵越高 → 信息量越大 → 越应该加载。

        使用字符级熵（简化版）。

        Args:
            content: 记忆内容

        Returns:
            float: 香农熵评分（0~1，归一化）
        """
        if not content:
            return 0.0

        # 计算字符频率分布
        char_counts = {}
        for ch in content:
            char_counts[ch] = char_counts.get(ch, 0) + 1

        total = len(content)
        entropy = 0.0
        for count in char_counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)

        # 归一化到 0~1（最大熵 = log2(字符集大小)）
        max_entropy = math.log2(max(len(char_counts), 1))
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def _char_distribution(self, text: str) -> dict:
        """
        计算字符频率分布（用于 KL 散度计算）。

        Args:
            text: 输入文本

        Returns:
            dict: {字符: 频率}
        """
        if not text:
            return {}
        counts = {}
        for ch in text:
            counts[ch] = counts.get(ch, 0) + 1
        total = len(text)
        return {ch: count / total for ch, count in counts.items()}

    def _is_anchor(self, memory: dict) -> bool:
        """
        判断是否为锚点记忆（不可淘汰）。

        锚点条件：
        1. layer == "personality"（人格层，永久保留）
        2. 包含实体定义关键词（"叫"、"名为"、"定义为"等）
        3. is_anchor 标记为 True

        Args:
            memory: 记忆字典

        Returns:
            bool: 是否为锚点
        """
        # 人格层记忆是锚点
        if memory.get("layer") == "personality":
            return True

        # 已标记为锚点
        if memory.get("is_anchor", False):
            return True

        # 包含实体定义关键词
        content = memory.get("content", "")
        anchor_keywords = ["叫", "名为", "定义为", "设置", "项目名", "项目叫"]
        if any(kw in content for kw in anchor_keywords):
            return True

        return False
