"""
Logistic Growth 模型 — 记忆容量管理（V2：宽进严出 + LLM动态K）

科学依据：生态学种群增长模型（Verhulst, 1838）
公式：dN/dt = rN(1 - N/K)

V2 设计哲学（宽进严出）：
- 写入不过滤：get_write_probability 始终返回 1.0（宽进）
- 淘汰加速：eviction_score = (N/K)^α，α > 1 时淘汰加速（严出）
- 淘汰触发：由 LLM 动态评估 α 值，不再使用固定阶段阈值
- K 动态计算：由 LLM 根据硬件资源、检索延迟目标、用户活跃度动态计算

参数科学依据：
- K = 运行时由 LLM 根据硬件和使用模式动态计算（默认 10000）
- r = 0.15：学习曲线理论，约 5 轮对话增长 50%
- α = 1.5：幂律裁剪指数，α > 1 时 N 越大淘汰压力越大（LLM 动态调整）

参考：ADR-008 记忆系统联动架构，ADR-009 动态淘汰策略
"""

import logging
import math
import random

logger = logging.getLogger("long_agent.algorithms.logistic_growth")


class MemoryCapacityManager:
    """
    记忆容量管理器 — Logistic Growth 模型（V2：宽进严出 + LLM动态K）

    职责：
    - 跟踪当前记忆数量 N
    - 计算写入概率（始终 1.0，宽进）
    - 计算淘汰评分（N/K)^α，严出）
    - 判断是否需要淘汰
    - K 动态计算：通过 LLM 评估硬件资源和使用模式，动态确定最优容量上限

    被以下模块使用：
    - src/memory/manager.py (MemoryManager.__init__)
    - tests/unit/test_memory_evictor.py (TestMemoryCapacityManager)
    """

    K_MIN = 5000
    K_MAX = 100000

    def __init__(self, K: int = 10000, alpha: float = 1.5, r: float = 0.15,
                 llm_evaluator: callable = None):
        """
        Args:
            K: 容量上限默认值（运行时由 LLM 动态计算覆盖）
            alpha: 幂律裁剪指数（α > 1 时 N 越大淘汰压力越大）
            r: 学习曲线增长率（约 5 轮对话增长 50%）
            llm_evaluator: LLM 评估函数，接收 prompt str，返回 str（异步）
                          签名：async (prompt: str) -> str
        """
        self._K = K
        self._K_default = K
        self._alpha = alpha
        self._r = r
        self._N = 0
        self._llm_evaluator = llm_evaluator
        self._eviction_threshold = 0.85  # 淘汰阈值：eviction_score > 0.85 时触发
        self._k_initialized = False  # 标记是否已完成动态K计算

    @property
    def K(self) -> int:
        return self._K

    @property
    def alpha(self) -> float:
        return self._alpha

    @property
    def current_count(self) -> int:
        return self._N

    async def async_initialize(self) -> None:
        """
        启动时调用：通过 LLM 动态计算最优 K 值。
        若无 LLM 评估器，使用默认 K 值。
        """
        if self._k_initialized:
            return
        if self._llm_evaluator:
            try:
                new_k = await self._compute_k_dynamic()
                self._K = new_k
                logger.info(f"LLM 动态计算 K 完成：{self._K_default} → {self._K}")
            except Exception as e:
                logger.warning(f"LLM 动态计算 K 失败，使用默认值 {self._K_default}：{e}")
        else:
            logger.info(f"无 LLM 评估器，使用默认 K={self._K_default}")
        self._k_initialized = True

    async def _compute_k_dynamic(self) -> int:
        """
        调用 LLM 评估最佳记忆容量 K（K_MIN ~ K_MAX 之间）。

        根据硬件资源、检索延迟目标、用户活跃度等因素，
        由 LLM 综合评估返回最优 K 值。

        Returns:
            int: 动态计算的 K 值（已裁剪到 [K_MIN, K_MAX] 范围）
        """
        prompt = (
            "根据以下信息评估最佳记忆容量K（5000~100000之间）：\n"
            " - 单条记忆平均大小：约500字节\n"
            " - 用户日对话量：约50条\n"
            " - 硬件：本地SQLite\n"
            "只返回一个数字，不要其他内容。"
        )
        result = await self._llm_evaluator(prompt)
        k = int(result.strip())
        clamped = max(self.K_MIN, min(self.K_MAX, k))
        logger.info(f"LLM 评估原始 K={k}，裁剪后 K={clamped}")
        return clamped

    def _ensure_k_initialized(self) -> None:
        """
        确保 K 已完成动态计算（同步检查）。
        若 async_initialize() 未被调用过，回退到默认 K 值并告警。
        """
        if not self._k_initialized:
            logger.warning(
                "async_initialize() 未被调用，使用默认 K="
                f"{self._K_default}。建议在初始化时调用 async_initialize()。"
            )
            self._k_initialized = True

    def update_count(self, N: int) -> None:
        """更新当前记忆数量"""
        self._N = max(0, N)

    def get_write_probability(self, N: int = None) -> float:
        """
        获取写入概率（宽进：始终返回 1.0）

        V2 设计：写入不过滤，淘汰阶段统一处理
        """
        return 1.0

    def get_eviction_score(self, N: int = None) -> float:
        """
        计算淘汰评分：(N/K)^α

        - N/K → 当前容量占用率（0~1）
        - α > 1 时，占用率越高淘汰压力越大（非线性增长）
        - α = 1.5 时：50% 占用 → 0.354，90% 占用 → 0.854，95% 占用 → 0.927

        Returns:
            float: 淘汰评分（0~1）
        """
        self._ensure_k_initialized()
        n = N if N is not None else self._N
        ratio = min(n / self._K, 1.0) if self._K > 0 else 1.0
        return math.pow(ratio, self._alpha)

    def should_evict(self, N: int = None) -> bool:
        """
        判断是否需要淘汰

        当 eviction_score > eviction_threshold (0.85) 时触发淘汰
        """
        self._ensure_k_initialized()
        return self.get_eviction_score(N) > self._eviction_threshold

    def get_phase(self, N: int = None) -> str:
        """
        获取当前阶段

        Returns:
            "normal" — 正常阶段（eviction_score <= 0.85）
            "eviction" — 淘汰阶段（eviction_score > 0.85）
        """
        if self.should_evict(N):
            return "eviction"
        return "normal"

    def get_eviction_candidates(self, memories: list, limit: int = None) -> list:
        """
        获取淘汰候选列表（按评分升序，低分优先淘汰）

        Args:
            memories: 记忆列表，每项需有 access_count 字段
            limit: 淘汰数量上限（None 时自动计算）

        Returns:
            需要淘汰的记忆列表
        """
        if not memories:
            return []

        # 计算目标淘汰数量
        if limit is None:
            n = self._N
            target = int(n * 0.1)  # 淘汰 10%
            limit = max(target, 1)

        # 按 access_count 升序排列（低访问先淘汰）
        sorted_memories = sorted(memories, key=lambda m: m.get("access_count", 0))
        return sorted_memories[:limit]

    def get_stats(self) -> dict:
        """获取容量统计信息"""
        return {
            "K": self._K,
            "N": self._N,
            "alpha": self._alpha,
            "utilization": self._N / self._K if self._K > 0 else 0,
            "eviction_score": self.get_eviction_score(),
            "phase": self.get_phase(),
            "should_evict": self.should_evict(),
        }
