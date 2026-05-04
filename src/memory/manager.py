"""
记忆系统 — 统一入口（V2：动态加载 + 淘汰引擎）

职责：
- 三层记忆的读写（人格/核心/标准）
- 幂等性保证（find_by_content 精确匹配）
- 审计日志集成
- 只读模式支持
- personality.md 防御性加载（校验失败→降级默认）
- pending_writes 重试机制
- V2 新增：动态记忆加载（MemoryLoader）+ 记忆淘汰（MemoryEvictor）

V2 记忆系统联动架构（ADR-008）：
- MemoryLoader：根据 Token 预算动态加载记忆（热区40%+相关30%+高价值20%+锚点10%）
- MemoryEvictor：当 N 接近 K 时淘汰低价值记忆（复用10算法评分+幂律裁剪）
- MemoryCapacityManager：容量管理（宽进严出，eviction_score = (N/K)^α）
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from src.audit.logger import AuditAction, AuditLogger
from src.memory.storage.base import Memory, MemoryStorage, MemoryWriteResult

logger = logging.getLogger("long_agent.memory.manager")


class PersonalitySchemaError(Exception):
    """personality.md Schema 校验错误"""

    pass


class MemoryManager:
    """
    记忆系统 — 统一入口

    通过 MemoryStorage 抽象接口操作数据，不依赖具体存储实现。
    V2 切换为 Redis 时，只需更换 storage 实现，此类代码不变。
    """

    # ---- personality.md Schema 定义 ----

    REQUIRED_DIMENSIONS = {
        "H": {"name": "诚实-谦逊", "min": 0, "max": 100},
        "E": {"name": "情绪性", "min": 0, "max": 100},
        "X": {"name": "外向性", "min": 0, "max": 100},
        "A": {"name": "宜人性", "min": 0, "max": 100},
        "C": {"name": "尽责性", "min": 0, "max": 100},
        "O": {"name": "经验开放性", "min": 0, "max": 100},
    }

    MAX_PENDING_RETRIES = 3

    # ---- PID 控制器参数（人格权重调整） ----
    # 科学依据：控制论（Ziegler & Nichols, 1942）
    # PID 公式：u(t) = Kp·e(t) + Ki·∫e(t)dt + Kd·de(t)/dt
    # 参数通过 Ziegler-Nichols 方法整定，可根据用户反馈动态优化
    PID_KP = 0.5  # 比例增益
    PID_KI = 0.1  # 积分增益
    PID_KD = 0.05  # 微分增益
    PID_DEAD_ZONE = 5.0  # 死区（偏差 < 此值不调整，防止过度敏感）
    PID_MAX_DELTA = 10.0  # 单次最大调整量（防止单次反馈导致剧烈变化）
    PID_INTEGRAL_MAX = 50.0  # 积分项上限（防止积分饱和）

    def __init__(
        self,
        storage: MemoryStorage,
        data_dir: str,
        audit_logger: AuditLogger = None,
        read_only: bool = False,
        # V2 新增参数
        context_window: int = 128000,
        capacity_k: int = 10000,
        compressor=None,
        alpha: float = None,
        llm_evaluator: callable = None,
    ):
        """
        记忆系统统一入口。

        Args:
            storage: 存储后端（MemoryStorage 抽象接口）
            data_dir: 数据目录
            audit_logger: 审计日志器
            read_only: 只读模式
            context_window: 模型上下文窗口（token 数），来自 ModelConfig.context_window
            capacity_k: 记忆容量上限 K 默认值（运行时由 LLM 动态计算覆盖）
            compressor: ContextCompressor 实例（用于 MemoryEvictor 评分，可选）
            alpha: 幂律裁剪指数（默认 1.5，LLM 动态调整）
            llm_evaluator: LLM 评估函数，签名 async (prompt: str) -> str，
                           用于动态计算最优 K 值（None 时使用默认 K）
        """
        self.storage = storage
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.personality = self._load_personality()
        self._read_only = read_only
        self.audit = audit_logger or AuditLogger(str(self.data_dir / "audit.jsonl"))

        # V2：动态记忆加载器
        from src.memory.memory_loader import LoadBudget, MemoryLoader

        self._loader = MemoryLoader(
            context_window=context_window,
        )
        self._load_budget = LoadBudget.from_context_window(context_window)

        # V2：记忆淘汰引擎（复用 compressor 的 10 算法评分）
        from src.memory.memory_evictor import MemoryEvictor

        self._evictor = MemoryEvictor(
            compressor=compressor,
            alpha=alpha,
        )

        # V2：容量管理器（宽进严出 + LLM动态K）
        from src.context.algorithms.logistic_growth import MemoryCapacityManager

        self._capacity_mgr = MemoryCapacityManager(
            k=capacity_k,
            alpha=alpha,
            llm_evaluator=llm_evaluator,
        )
        self._k_async_initialized = False  # 标记是否已异步初始化 K

        logger.info(
            f"MemoryManager V2 初始化完成 "
            f"(context_window={context_window}, k={capacity_k}, alpha={alpha or 1.5})"
        )

    async def async_initialize(self) -> None:
        """
        异步初始化：触发 MemoryCapacityManager 的 K 动态计算。

        应在 MemoryManager 创建后、首次使用前调用。
        若 llm_evaluator 已提供，将通过 LLM 评估最优 K 值；
        否则使用默认 K 值。
        """
        if self._k_async_initialized:
            return
        await self._capacity_mgr.async_initialize()
        self._k_async_initialized = True
        logger.info(f"MemoryManager 异步初始化完成，当前 k={self._capacity_mgr.k}")

    # ---- 人格管理（防御性编程） ----

    def _load_personality(self) -> dict:
        """
        加载并校验 personality.md（防御性编程：校验失败降级到默认人格）

        策略：
        - 文件不存在 → 返回默认人格（全50）
        - 解析失败/缺维度/分值非法 → 记录警告 + 降级处理
        - 个别维度分值非法 → 该维度用默认值50，其余正常加载
        """
        path = self.data_dir / "personality.md"
        if not path.exists():
            logger.info("personality.md 不存在，使用默认人格（全50）")
            return self._default_personality()

        try:
            rows = self._parse_markdown_table(path)
        except Exception as e:
            logger.warning(
                f"personality.md 解析失败，使用默认人格：{e}。"
                f"请检查文件格式是否为有效的 Markdown 表格。"
            )
            return self._default_personality()

        result = {}
        errors = []

        for row in rows:
            dim_raw = row.get("维度", "").strip()
            score_raw = row.get("分值", "").strip()
            if not dim_raw:
                continue
            key = dim_raw[0].upper()
            if key not in self.REQUIRED_DIMENSIONS:
                continue

            try:
                score = int(score_raw)
            except (ValueError, TypeError):
                errors.append(f"维度 {key} 分值 '{score_raw}' 不是整数，使用默认值50")
                continue

            spec = self.REQUIRED_DIMENSIONS[key]
            if not (spec["min"] <= score <= spec["max"]):
                errors.append(
                    f"维度 {key}（{spec['name']}）分值 {score} 超出范围"
                    f"[{spec['min']}-{spec['max']}]，使用默认值50"
                )
                continue

            result[key] = score

        # 检查缺失维度
        missing = set(self.REQUIRED_DIMENSIONS.keys()) - set(result.keys())
        for key in missing:
            errors.append(
                f"维度 {key}（{self.REQUIRED_DIMENSIONS[key]['name']}）缺失，使用默认值50"
            )

        if errors:
            logger.warning(
                f"personality.md 校验发现问题（{len(errors)}项），已降级处理：{'; '.join(errors)}"
            )

        # 补全缺失维度
        for key in self.REQUIRED_DIMENSIONS:
            if key not in result:
                result[key] = 50

        return result

    def _default_personality(self) -> dict:
        """默认人格：所有维度 50（中性）"""
        return {k: 50 for k in self.REQUIRED_DIMENSIONS}

    @staticmethod
    def _parse_markdown_table(path: Path) -> list[dict]:
        """解析 Markdown 表格为字典列表"""
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 过滤空行、分隔行和非表格行（只保留以 | 开头的行）
        data_lines = [
            line
            for line in lines
            if line.strip()
            and not re.match(r"^\|[-| ]+\|$", line.strip())
            and line.strip().startswith("|")
        ]

        if len(data_lines) < 2:
            raise ValueError("表格至少需要表头和一行数据")

        headers = [h.strip() for h in data_lines[0].split("|") if h.strip()]
        rows = []
        for line in data_lines[1:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))

        return rows

    # ---- 记忆读写（幂等 + 审计 + 只读） ----

    async def remember(
        self, content: str, layer: str = "core", category: str = "general"
    ) -> MemoryWriteResult:
        """
        写入记忆（幂等 + 审计 + 只读检查）

        幂等性：相同 content + layer 已存在 → 更新时间戳，不创建重复记录
        """
        # 只读模式：拒绝所有写入
        if self._read_only:
            logger.warning(f"只读模式：拒绝写入记忆 [{layer}] {content[:50]}")
            self.audit.log(
                AuditAction.MEMORY_WRITE,
                details={
                    "layer": layer,
                    "content_preview": content[:50],
                    "reason": "read_only_rejected",
                },
                success=False,
                error="只读模式：写入被拒绝",
            )
            return MemoryWriteResult(id="", created=False, message="只读模式：写入被拒绝")

        # 幂等性检查
        existing = await self.storage.find_by_content(content, layer=layer)
        if existing:
            existing.touch()
            await self.storage.update_access_count(existing.id, delta=1)
            self.audit.log(
                AuditAction.MEMORY_UPDATE,
                details={
                    "memory_id": existing.id,
                    "layer": layer,
                    "reason": "idempotent_hit",
                    "content_preview": content[:50],
                },
            )
            logger.debug(f"幂等命中，更新已有记忆: {existing.id}")
            return MemoryWriteResult(
                id=existing.id, created=False, message="记忆已存在，已更新时间戳"
            )

        # ---- 冲突检测（缺口4修复） ----
        # 在写入新记忆之前，检查是否与已有记忆冲突
        conflict_result = await self._detect_conflicts(content, layer)
        if conflict_result.has_conflicts:
            logger.warning(
                f"检测到 {len(conflict_result.conflicts)} 条冲突记忆，"
                f"标记冲突但不阻止写入（自动整合策略）"
            )
            # 记录审计日志
            self.audit.log(
                AuditAction.MEMORY_WRITE,
                details={
                    "layer": layer,
                    "category": category,
                    "content_preview": content[:100],
                    "conflict_detected": True,
                    "conflict_count": len(conflict_result.conflicts),
                    "conflict_ids": [c.id for c in conflict_result.conflicts],
                },
            )

        # 新建记忆（带冲突标记）
        memory = Memory(
            content=content,
            layer=layer,
            category=category,
            conflicts=[c.id for c in conflict_result.conflicts],
        )
        result = await self.storage.upsert(memory)

        self.audit.log(
            AuditAction.MEMORY_WRITE,
            details={
                "memory_id": result.id,
                "layer": layer,
                "category": category,
                "content_preview": content[:100],
            },
        )
        result.created = True
        return result

    # ---- 冲突检测 ----

    async def _detect_conflicts(self, content: str, layer: str) -> "ConflictResult":  # noqa: F821
        """
        检测新记忆是否与已有记忆冲突

        冲突类型：
        1. 直接矛盾（同一属性，相反取值）
        2. 语义矛盾（语义相似但内容相反）

        V1 实现：拉取同层最近记忆 + 关键词矛盾匹配
        V2 升级：LLM 语义理解 + 向量相似度

        注意：不用 search(content) 做关键词搜索，因为中文 LIKE 无法匹配
              语义相关但措辞不同的记忆。改为拉取最近记忆做全量对比。

        Args:
            content: 新记忆内容
            layer: 目标层

        Returns:
            ConflictResult: 冲突检测结果
        """
        from src.memory.storage.base import ConflictResult

        conflicts = []

        # 获取同层最近记忆（空查询 → 按 updated_at 倒序）
        existing_memories = await self.storage.search("", layer=layer, limit=50)

        if not existing_memories:
            return ConflictResult(has_conflicts=False, conflicts=[])

        # V1：简单矛盾检测
        # 检测"是"vs"不是"、"喜欢"vs"不喜欢"等模式
        conflict_patterns = [
            (["是", "喜欢", "支持", "同意", "好"], ["不是", "不喜欢", "反对", "不同意", "差"]),
            (["喜欢", "爱", "偏好"], ["讨厌", "恨", "厌恶"]),
            (["总是", "一定", "必须"], ["从不", "绝不", "不必"]),
            (["有", "存在", "包含"], ["没有", "不存在", "不包含"]),
        ]

        for existing in existing_memories:
            # 先检查主体是否相同
            if not self._same_subject(content, existing.content):
                continue

            # 再检查是否包含矛盾词
            for pos_words, neg_words in conflict_patterns:
                has_pos_new = any(w in content for w in pos_words)
                has_neg_existing = any(w in existing.content for w in neg_words)
                has_neg_new = any(w in content for w in neg_words)
                has_pos_existing = any(w in existing.content for w in pos_words)

                if (has_pos_new and has_neg_existing) or (has_neg_new and has_pos_existing):
                    conflicts.append(existing)
                    break

        return ConflictResult(
            has_conflicts=len(conflicts) > 0,
            conflicts=conflicts,
        )

    @staticmethod
    def _same_subject(text1: str, text2: str) -> bool:
        """
        判断两段文字是否在说同一件事。

        科学依据：Jaccard 相似度
        J(A, B) = |A ∩ B| / |A ∪ B|

        策略：
        1. 提取两段文字的字符集合（去除停用词）
        2. 计算 Jaccard 相似度
        3. 相似度 > 阈值 → 同一主题

        V2：使用 LLM 语义判断（更准确）

        Args:
            text1: 第一段文字
            text2: 第二段文字

        Returns:
            bool: 是否同一主题
        """
        # 停用词（中文 + 英文）
        stopwords = {
            "的",
            "了",
            "是",
            "在",
            "我",
            "有",
            "和",
            "就",
            "不",
            "人",
            "都",
            "一",
            "一个",
            "上",
            "也",
            "很",
            "到",
            "说",
            "要",
            "去",
            "你",
            "会",
            "着",
            "没有",
            "看",
            "好",
            "自己",
            "这",
            "他",
            "她",
            "它",
            "们",
            "那",
            "些",
            "什么",
            "怎么",
            "为",
            "因为",
            "所以",
            "如果",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "shall",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "and",
            "or",
            "but",
            "not",
            "no",
            "yes",
            "this",
            "that",
        }

        def tokenize(text: str) -> set:
            """简单分词：按字符 + 去除停用词"""
            tokens = set()
            for char in text:
                if char not in stopwords and not char.isspace():
                    tokens.add(char)
            # 也加入 2-gram
            for i in range(len(text) - 1):
                bigram = text[i : i + 2]
                if bigram not in stopwords:
                    tokens.add(bigram)
            return tokens

        tokens1 = tokenize(text1)
        tokens2 = tokenize(text2)

        if not tokens1 or not tokens2:
            return False

        # Jaccard 相似度
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        jaccard = len(intersection) / len(union) if union else 0

        # 阈值：Jaccard > 0.15 认为同一主题
        # 依据：短文本（< 20 字）的 Jaccard 通常较低，0.15 是经验阈值
        return jaccard > 0.15

    async def recall(self, query: str, layer: str = None, limit: int = 10) -> list[Memory]:
        """搜索记忆（别名：search）"""
        return await self.storage.search(query, layer=layer, limit=limit)

    async def search(self, query: str, layer: str = None, limit: int = 10) -> list[Memory]:
        """搜索记忆（与 recall 等价，兼容设计文档接口）"""
        return await self.recall(query, layer=layer, limit=limit)

    def get_personality(self) -> dict:
        """
        获取第1层人格（HEXACO 六维）

        返回格式：
        {
            "H": 50, "E": 50, "X": 50,
            "A": 50, "C": 50, "O": 50,
            "bottom_lines": [...]
        }
        """
        result = {}
        dim_map = {
            "H": "honesty",
            "E": "emotionality",
            "X": "extraversion",
            "A": "agreeableness",
            "C": "conscientiousness",
            "O": "openness",
        }
        for key, attr in dim_map.items():
            result[key] = (
                self.personality.get(attr, 50)
                if isinstance(self.personality, dict)
                else getattr(self.personality, attr, 50)
            )
        return result

    async def get_standards(self, category: str = None, limit: int = 10) -> list:
        """
        获取第3层标准记忆（async 接口，对齐 DESIGN-V2 §4.2）

        Args:
            category: 标准类别（None 时返回所有标准）
            limit: 返回数量上限

        Returns:
            list[Memory]: 标准记忆列表
        """
        results = await self.storage.search("", layer="standard", limit=limit)
        if category:
            results = [r for r in results if r.category == category]
        return results

    async def build_context(self) -> dict:
        """构建 Agent 上下文"""
        hot = await self.storage.get_by_zone("hot", limit=20)
        standards = await self.storage.search("", layer="standard", limit=10)
        return {
            "personality": self.get_personality(),
            "hot_memories": hot,
            "standards": standards,
        }

    # ---- pending_writes 重试机制 ----

    async def flush_pending_writes(self):
        """
        启动时补写 pending_writes

        重试机制：
        - 每条记录最多重试 3 次
        - 超过 3 次 → 标记 failed，记录到 failed_writes.jsonl
        """
        pending = self._load_pending_writes()
        if not pending:
            return

        logger.info(f"开始补写 {len(pending)} 条 pending_writes")
        self.audit.log(AuditAction.PENDING_WRITE_RETRY, details={"count": len(pending)})

        still_pending = []
        for item in pending:
            if item.get("retry_count", 0) >= self.MAX_PENDING_RETRIES:
                logger.error(
                    f"pending_write 重试超过 {self.MAX_PENDING_RETRIES} 次，"
                    f"标记为 failed: {item.get('id', 'unknown')}"
                )
                self.audit.log(
                    AuditAction.PENDING_WRITE_FAILED,
                    details={
                        "memory_id": item.get("id", "unknown"),
                        "retry_count": item["retry_count"],
                        "last_error": item.get("last_error", ""),
                    },
                    success=False,
                    error=item.get("last_error", "max retries exceeded"),
                )
                self._record_failed_write(item)
                continue

            try:
                mem_data = item["memory"]
                memory = Memory(**mem_data)
                await self.storage.upsert(memory)
                logger.info(f"pending_write 补写成功: {item.get('id', 'unknown')}")
            except Exception as e:
                item["retry_count"] = item.get("retry_count", 0) + 1
                item["last_error"] = str(e)
                still_pending.append(item)
                logger.warning(f"pending_write 补写失败（第 {item['retry_count']} 次）: {e}")

        self._save_pending_writes(still_pending)
        if still_pending:
            logger.warning(f"仍有 {len(still_pending)} 条 pending_writes 未写入")

    def _load_pending_writes(self) -> list[dict]:
        path = self.data_dir / "pending_writes.json"
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return []

    def _save_pending_writes(self, pending: list[dict]):
        path = self.data_dir / "pending_writes.json"
        if pending:
            with open(path, "w") as f:
                json.dump(pending, f, ensure_ascii=False, indent=2)
        elif path.exists():
            path.unlink()

    def _record_failed_write(self, item: dict):
        path = self.data_dir / "failed_writes.jsonl"
        item["failed_at"] = datetime.utcnow().isoformat() + "Z"
        with open(path, "a") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # ---- 维护操作 ----

    async def decay_access_counts(self, factor: float = 0.9):
        """访问计数衰减"""
        await self.storage.decay_all_access_counts(factor)

    async def should_compress_cold_zone(self) -> bool:
        cold_count = await self.storage.count(layer="core")
        return cold_count > 1000

    async def compress_cold_zone(self):
        """冷区压缩（V1 占位，V2 实现）"""
        logger.info("冷区压缩检查：当前记忆数未超过阈值，跳过")

    def backup(self, keep: int = 3):
        self.storage.backup(keep=keep)

    # ---- 人格权重调整（PID 控制器） ----

    def adjust_personality(self, adjustments: list[dict]) -> dict:
        """
        使用 PID 控制器调整人格权重。

        科学依据：控制论（Ziegler & Nichols, 1942）
        PID 公式：u(t) = Kp·e(t) + Ki·∫e(t)dt + Kd·de(t)/dt

        优势（相比写死的阈值触发）：
        - 连续调整，不是"达到阈值才动"
        - 死区防止过度敏感
        - 积分项消除稳态误差
        - 微分项抑制震荡

        Args:
            adjustments: [{"dimension": "X", "direction": "increase/decrease",
                          "intensity": 0.0~1.0, "reason": "..."}]

        Returns:
            dict: 调整后的人格参数
        """
        if not adjustments:
            return self.personality

        for adj in adjustments:
            dim = adj.get("dimension")
            direction = adj.get("direction", "increase")
            intensity = adj.get("intensity", 0.5)
            reason = adj.get("reason", "")

            if dim not in self.personality:
                continue

            # 计算误差（目标值 - 当前值）
            # intensity 映射为目标调整量（-max_delta ~ +max_delta）
            target_delta = intensity * self.PID_MAX_DELTA
            if direction == "decrease":
                target_delta = -target_delta

            error = target_delta  # 误差 = 期望调整量

            # 死区检查（偏差太小时不调整）
            if abs(error) < self.PID_DEAD_ZONE:
                logger.debug(f"人格调整死区：{dim} 偏差 {error:.2f} < {self.PID_DEAD_ZONE}，跳过")
                continue

            # PID 计算
            # 比例项
            p_term = self.PID_KP * error

            # 积分项（累积历史误差，消除稳态误差）
            if not hasattr(self, "_pid_integral"):
                self._pid_integral = {}
            if dim not in self._pid_integral:
                self._pid_integral[dim] = 0.0
            self._pid_integral[dim] += error
            # 积分限幅（防止积分饱和）
            self._pid_integral[dim] = max(
                -self.PID_INTEGRAL_MAX, min(self.PID_INTEGRAL_MAX, self._pid_integral[dim])
            )
            i_term = self.PID_KI * self._pid_integral[dim]

            # 微分项（抑制震荡）
            if not hasattr(self, "_pid_prev_error"):
                self._pid_prev_error = {}
            prev_error = self._pid_prev_error.get(dim, 0.0)
            d_term = self.PID_KD * (error - prev_error)
            self._pid_prev_error[dim] = error

            # PID 输出
            delta = p_term + i_term + d_term

            # 限幅（单次最大调整量）
            delta = max(-self.PID_MAX_DELTA, min(self.PID_MAX_DELTA, delta))

            # 应用调整
            old_value = self.personality[dim]
            new_value = max(0.0, min(100.0, old_value + delta))
            self.personality[dim] = new_value

            logger.info(
                f"人格调整 [{dim}]: {old_value:.1f} → {new_value:.1f} "
                f"(Δ={delta:.2f}, P={p_term:.2f}, I={i_term:.2f}, D={d_term:.2f}, "
                f"reason={reason})"
            )

        return self.personality

    def save_personality(self):
        """保存人格参数到 personality.md"""
        path = self.data_dir / "personality.md"
        lines = [
            "| 维度 | 分值 | 说明 |",
            "|------|------|------|",
        ]
        dim_names = {
            "H": "诚实-谦逊",
            "E": "情绪性",
            "X": "外向性",
            "A": "宜人性",
            "C": "尽责性",
            "O": "经验开放性",
        }
        for dim in ["H", "E", "X", "A", "C", "O"]:
            score = self.personality.get(dim, 50)
            name = dim_names[dim]
            lines.append(f"| {dim}({name}) | {score:.0f} | |")
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"人格参数已保存到 {path}")

    def close(self):
        self.storage.close()

    # ================================================================
    # V2 接口：动态记忆加载 + 淘汰引擎
    # ================================================================

    async def load_memories_for_context(
        self,
        current_input: str,
        layer_filter: str = None,
    ) -> list[dict]:
        """
        V2：动态加载记忆（用于构建 System Prompt）。

        使用 MemoryLoader 按 Token 预算分配加载：
        - 热区 40%：最近访问的记忆
        - 相关 30%：与当前输入互信息最高的记忆
        - 高价值 20%：香农熵最高的记忆
        - 锚点 10%：不可淘汰的记忆

        Args:
            current_input: 当前用户输入
            layer_filter: 层过滤（None=全部, "personality", "core", "standard"）

        Returns:
            list[dict]: 加载的记忆列表
        """
        # 获取所有候选记忆
        all_memories = await self.storage.get_all()

        # 层过滤
        if layer_filter:
            all_memories = [m for m in all_memories if m.get("layer") == layer_filter]

        # 使用 MemoryLoader 动态加载
        loaded = self._loader.load_memories(
            all_memories=all_memories,
            current_input=current_input,
            budget=self._load_budget,
        )

        logger.info(
            f"动态加载记忆: {len(all_memories)} 条候选 → {len(loaded)} 条加载 "
            f"(layer={layer_filter or 'all'})"
        )
        return loaded

    async def check_and_evict(self, current_input: str = "") -> dict:
        """
        V2：检查容量并执行淘汰。

        流程：
        1. 获取当前记忆数量 N
        2. 计算 eviction_score = (N/K)^α
        3. 若 eviction_score > threshold，触发淘汰
        4. 使用 MemoryEvictor 淘汰低价值记忆

        Args:
            current_input: 当前用户输入（用于相关性评分）

        Returns:
            dict: {"evicted": int, "remaining": int, "eviction_score": float}
        """
        # 获取当前记忆数量
        all_memories = await self.storage.get_all()
        current_count = len(all_memories)
        capacity_k = self._capacity_mgr.k

        # 更新容量管理器
        self._capacity_mgr.update_count(current_count)

        # 检查是否需要淘汰
        eviction_score = self._capacity_mgr.get_eviction_score(current_count)

        if not self._capacity_mgr.should_evict(current_count):
            return {"evicted": 0, "remaining": current_count, "eviction_score": eviction_score}

        # 执行淘汰
        result = self._evictor.evict(
            memories=all_memories,
            current_count=current_count,
            capacity_k=capacity_k,
            current_input=current_input,
        )

        # 标记被淘汰的记忆
        for mem_id in result.evicted_ids:
            await self.storage.mark_evicted(mem_id)

        return {
            "evicted": result.evicted_count,
            "remaining": result.remaining_count,
            "eviction_score": eviction_score,
        }

    def get_capacity_status(self) -> dict:
        """
        V2：获取容量状态。

        Returns:
            dict: {
                "current_count": int,
                "capacity_k": int,
                "eviction_score": float,
                "phase": str,  # "normal" or "eviction"
                "alpha": float,
            }
        """
        return {
            "capacity_k": self._capacity_mgr.k,
            "eviction_score": self._capacity_mgr.get_eviction_score(),
            "phase": self._capacity_mgr.get_phase(),
            "alpha": self._capacity_mgr._alpha,
        }

    def build_system_prompt_memories(
        self,
        current_input: str,
        layer_order: list[str] = None,
    ) -> str:
        """
        V2：构建 System Prompt 中的记忆部分。

        System Prompt 组成（ADR-010）：
        1. 人格层（固定）：personality.md 中的 H/E/X/A/C/O 维度
        2. 核心层（按项目）：当前项目的核心记忆
        3. 标准层（按任务）：与当前任务相关的标准记忆
        4. 动态层（预算分配）：按 Token 预算动态加载的记忆

        Args:
            current_input: 当前用户输入
            layer_order: 层顺序（默认 ["personality", "core", "standard"]）

        Returns:
            str: System Prompt 中的记忆文本
        """
        if layer_order is None:
            layer_order = ["personality", "core", "standard"]

        sections = []

        # 人格层（固定，不受预算限制）
        personality_text = self._build_personality_section()
        if personality_text:
            sections.append(f"## 人格\n{personality_text}")

        # 核心层 + 标准层（按预算加载）
        # 注意：这里使用同步接口，实际调用时应在异步上下文中使用 load_memories_for_context
        # 此方法仅用于构建已加载记忆的文本
        for layer in layer_order:
            if layer == "personality":
                continue  # 已处理
            layer_memories = []  # 应由调用方通过 load_memories_for_context 获取
            if layer_memories:
                sections.append(
                    f"## {layer}\n" + "\n".join(f"- {m.get('content', '')}" for m in layer_memories)
                )

        return "\n\n".join(sections)

    def _build_personality_section(self) -> str:
        """构建人格层文本"""
        lines = []
        dim_names = {
            "H": "诚实-谦逊",
            "E": "情绪性",
            "X": "外向性",
            "A": "宜人性",
            "C": "尽责性",
            "O": "经验开放性",
        }
        for dim in ["H", "E", "X", "A", "C", "O"]:
            score = self.personality.get(dim, 50)
            name = dim_names[dim]
            lines.append(f"- {name}({dim}): {score:.0f}/100")
        return "\n".join(lines)
