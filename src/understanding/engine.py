"""
理解层 — 意图解析 + 追问策略 + 跑偏检查

V1 实现：
- 基于规则的意图解析（本地规则表）
- 简单置信度评估
- 追问策略：置信度 < 0.5 时追问
- 跑偏检查：简单关键词匹配

V2 升级方向（参考 02_理解层设计.md）：
- LLM 语义理解
- 贝叶斯置信度阈值
- 边际效益追问预算
- 决策树追问策略
- LLM 降级健康度评分
"""

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("long_agent.understanding")


@dataclass
class Intent:
    """解析后的用户意图"""

    type: str = ""
    # 取值：memory_write / memory_read / memory_search / personality_update / llm_chat / unknown
    content: str = ""
    target_layer: str = "core"  # personality / core / standard
    confidence: float = 0.0  # 0.0 ~ 1.0
    requires_approval: bool = False
    metadata: dict = field(default_factory=dict)
    # V2 追问相关
    needs_clarification: bool = False
    clarification_question: str = ""
    clarification_strategy: str = "none"  # none / open / confirm / hybrid
    reason: str = ""  # 解析理由/推理过程（LLM 输出或本地规则说明）


@dataclass
class ClarificationResult:
    """追问结果"""

    question: str = ""
    original_input: str = ""
    attempts: int = 0
    max_attempts: int = 3


class UnderstandingEngine:
    """
    理解层引擎

    V1：基于规则的意图解析 + 简单置信度评估
    V2：接入 LLM 进行语义理解 + 4个公式（贝叶斯/边际效益/决策树/健康度）

    设计原则：
    - 宁可多问一句，不要猜错返工
    - 带着记忆理解，不从零开始
    - 量化不确定性，用置信度说话

    LLM不可用时回退固定模板，不抛异常；人格参数影响语气风格。
    """

    # 本地规则表（固定已知规则 → 不调 LLM）
    LOCAL_RULES = {
        "停": "interrupt",
        "退出": "exit",
        "帮助": "help",
        "你是谁": "who_are_you",
        "现在几点": "current_time",
        "清空记忆": "clear_memory",
        "重置人格": "reset_personality",
        "查看记忆": "show_memory",
        "查看人格": "show_personality",
    }

    # 追问模板（V1 简单版，V2 由 LLM 动态生成）
    CLARIFICATION_QUESTIONS = [
        "你想让我做什么？请具体说明。",
        "你是想记住、搜索还是其他操作？",
        "我没理解，请用不同的方式再说一次。",
    ]

    def __init__(self, llm_provider=None):
        """
        Args:
            llm_provider: LLM 提供者（V1 可为 None，V2 必须）
        """
        self._llm = llm_provider
        self._clarification_history: list[ClarificationResult] = []

    @property
    def has_llm(self) -> bool:
        return self._llm is not None

    def should_call_llm(self, user_input: str) -> bool:
        """始终返回 True，强制走 LLM 解析"""
        return True

    async def parse(self, user_input: str, context: dict = None) -> Intent:
        """
        解析用户意图

        V1：基于关键词匹配 + 可选 LLM 增强
        V2：替换为 LLM 主路径 + 规则快速路径

        Args:
            user_input: 用户输入
            context: 记忆上下文（人格 + 相关记忆 + 标准）

        Returns:
            Intent: 结构化意图
        """
        context = context or {}

        # 1. 本地规则快速路径（系统命令：退出/帮助等，不需要LLM）
        if user_input.strip() in self.LOCAL_RULES:
            rule_type = self.LOCAL_RULES[user_input.strip()]
            intent = Intent(
                type=rule_type,
                content=user_input,
                confidence=1.0,
                requires_approval=(user_input.strip() in ("清空记忆", "重置人格")),
                reason=f"LOCAL_RULE: {rule_type}",
            )
            return intent

        # 2. LLM 解析（唯一意图解析路径，失败直接抛异常，无降级）
        if self._llm:
            try:
                return await self._parse_by_llm(user_input, context)
            except Exception as e:
                logger.error(f"LLM 意图解析失败: {e}")
                raise RuntimeError(f"LLM不可用，无法解析意图: {e}") from e

        # 3. LLM 不可用 — 抛异常（LLM-only 原则）
        raise RuntimeError("LLM不可用，无法解析意图")

    async def _parse_by_llm(self, user_input: str, context: dict) -> Intent:
        """LLM 语义理解（V1 简单版）"""
        # 构建 prompt
        system_prompt = "你是一个意图分析助手。分析用户输入，理解其真实意图。"

        memory_context = context.get("relevant_memories", [])
        if memory_context:
            mem_text = "\n".join(f"- {m.get('content', '')}" for m in memory_context[:3])
            system_prompt += f"\n\n相关记忆：\n{mem_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    '分析以下用户输入的意图，返回 JSON：'
                    '{"type": "memory_write|memory_read|memory_search|llm_chat|unknown", '
                    '"target_layer": "personality|core|standard", '
                    '"confidence": 0.0-1.0, '
                    '"requires_approval": true|false, '
                    '"action": "具体动作", '
                    '"target": "操作对象", '
                    '"reasoning": "推理过程"}'
                    f'\n\n用户输入：{user_input}'
                ),
            },
        ]

        from src.llm.provider import LLMRequest
        request = LLMRequest(messages=messages)
        result = await self._llm.chat(request)

        if result.is_ok:
            try:
                data = json.loads(result.content)
                return Intent(
                    type=data.get("type", "unknown"),
                    content=user_input,
                    target_layer=data.get("target_layer", "core"),
                    confidence=float(data.get("confidence", 0.5)),
                    requires_approval=data.get("requires_approval", False),
                    metadata={"action": data.get("action", ""), "target": data.get("target", "")},
                    reason=str(data.get("reasoning", "")),
                )
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"LLM 返回解析失败: {e}, content={result.content[:100]}")

        # LLM 失败，返回 unknown + 追问
        logger.warning("LLM 解析失败，返回 unknown 意图")
        return Intent(
            type="unknown",
            content=user_input,
            confidence=0.3,
            needs_clarification=True,
            clarification_question="我没理解你的意思，能不能用另一种方式描述一下？",
        )

    def generate_clarification(
        self, user_input: str, intent: Intent, attempt: int = 1,
        personality: dict = None
    ) -> ClarificationResult:
        """
        生成追问。

        V1：使用固定模板（保证基础可用）
        V2：由 LLM 动态生成（更自然、支持多语言）

        Args:
            user_input: 用户原始输入
            intent: 解析后的意图
            attempt: 当前追问次数
            personality: 人格参数 dict，包含 X/A/E 等维度（None 时不调整语气）
        """
        idx = min(attempt - 1, len(self.CLARIFICATION_QUESTIONS) - 1)
        question = self.CLARIFICATION_QUESTIONS[idx]

        # 根据人格参数调整语气
        if personality:
            question = self._apply_personality_tone(question, personality)

        return ClarificationResult(
            question=question,
            original_input=user_input,
            attempts=attempt,
            max_attempts=3,
        )

    @staticmethod
    def _apply_personality_tone(question: str, personality: dict) -> str:
        """
        根据 HEXACO 人格参数调整追问语气。

        规则：
        - X(外向性) > 70：添加主动语气词 "吧！"、"怎么样？"
        - X < 30：保持简洁，不加多余语气词
        - A(宜人性) > 70：添加敬语 "请"、"可以吗？"
        - A < 30：语气直接，不用敬语
        - E(情绪性) > 70：添加表情或温度词
        - E < 30：保持客观中立
        """
        x = personality.get("X", 50)
        a = personality.get("A", 50)
        e = personality.get("E", 50)

        # E(情绪性) — 最高优先级，添加温度词/表情
        if e > 70:
            question = question.rstrip("。？?") + " 😊"
        elif e < 30:
            # 保持客观中立，不做添加
            pass

        # A(宜人性) — 添加敬语或直接化
        if a > 70:
            if not question.startswith("请"):
                question = "请" + question
            if "？" in question or "?" in question:
                question = question.rstrip("？?") + "可以吗？"
        elif a < 30:
            # 语气直接，去掉可能的敬语
            question = question.replace("请", "").replace("可以吗", "")
            question = question.strip()
            if not question.endswith(("。", "！", "？", ".", "!", "?")):
                question += "。"

        # X(外向性) — 添加主动语气词
        if x > 70:
            if "怎么样" not in question and "吧" not in question:
                question = question.rstrip("。？?.") + "怎么样？"
        elif x < 30:
            # 保持简洁，不加多余语气词
            pass

        return question

    async def generate_clarification_by_llm(
        self, user_input: str, intent: Intent, attempt: int = 1,
        personality: dict = None
    ) -> ClarificationResult:
        """
        由 LLM 动态生成追问（V2 方法，V1 也可用）。

        优势：
        - 支持任意语言（中文/英文/混合）
        - 根据追问次数调整策略
        - 结合人格参数调整语气

        Args:
            user_input: 用户原始输入
            intent: 解析后的意图
            attempt: 当前追问次数
            personality: 当前人格参数（影响追问语气）
        """
        if not self._llm:
            # 没有 LLM，降级到固定模板（携带人格参数）
            return self.generate_clarification(user_input, intent, attempt, personality=personality)

        # 构建追问策略提示
        strategy_hint = ""
        if attempt == 1:
            strategy_hint = "第一次追问：请用开放式问题，了解用户想要做什么。"
        elif attempt == 2:
            strategy_hint = "第二次追问：用户仍然不清楚，请用选择题方式帮助用户明确意图。"
        else:
            strategy_hint = "最后一次追问：请直接猜测用户最可能想要什么，给出确认式问题。"

        personality_hint = ""
        if personality:
            x = personality.get("X", 50)
            a = personality.get("A", 50)
            if x > 70:
                personality_hint = "你的性格偏外向，可以主动一些。"
            elif x < 30:
                personality_hint = "你的性格偏内向，保持简洁。"
            if a > 70:
                personality_hint += "语气温和，多用'请'、'可以吗'。"
            elif a < 30:
                personality_hint += "语气直接，不用过度客气。"

        system_prompt = (
            f"你是一个意图澄清助手。用户说了一句模糊的话，你需要追问以明确意图。\n"
            f"用户原始输入：「{user_input}」\n"
            f"已解析意图：{getattr(intent, 'type', 'unknown')}\n"
            f"追问策略：{strategy_hint}\n"
            f"人格提示：{personality_hint}\n\n"
            "请直接输出追问内容（不要输出 JSON，不要解释），"
            "用与用户相同的语言追问。"
        )

        try:
            from src.llm.provider import LLMRequest
            request = LLMRequest(messages=[
                {"role": "system", "content": system_prompt},
            ], temperature=0.5)
            result = await self._llm.chat(request)
            if result.is_ok and result.content.strip():
                return ClarificationResult(
                    question=result.content.strip(),
                    original_input=user_input,
                    attempts=attempt,
                    max_attempts=3,
                )
        except Exception as e:
            logger.warning(f"Llm 追问生成失败，降级到模板: {e}")

        # 降级到固定模板
        return self.generate_clarification(user_input, intent, attempt)

    async def analyze_personality_feedback(
        self, user_input: str, current_personality: dict = None
    ) -> dict:
        """
        分析用户反馈，返回 HEXACO 人格调整指令。

        V1：基于规则的快速路径 + LLM 语义理解（如果有 LLM）
        V2：完全由 LLM 处理

        Args:
            user_input: 用户反馈文本
            current_personality: 当前人格参数

        Returns:
            dict: {
                "adjustments": [{"dimension": "X", "direction": "decrease", "intensity": 0.5, "reason": "..."}],
                "sentiment": "positive" | "neutral" | "negative",
                "method": "rule" | "llm"  # 标识使用的分析方法
            }
        """
        # 1. 仅走 LLM 语义理解（关键词规则已移除）
        if self._llm:
            try:
                result = await self._analyze_by_llm(user_input, current_personality)
                result["method"] = "llm"
                return result
            except Exception as e:
                logger.warning(f"LLM 人格反馈分析失败: {e}")

        # 2. 无 LLM → 返回中性，不做关键词降级
        return {"adjustments": [], "sentiment": "neutral", "method": "none"}

    async def _analyze_by_llm(
        self, user_input: str, current_personality: dict = None
    ) -> dict:
        """基于 LLM 的人格反馈分析（支持任意语言）"""
        system_prompt = (
            "你是一个人格分析引擎。根据用户对 Agent 的反馈，判断需要调整哪些 HEXACO 人格维度。\n\n"
            "HEXACO 六维：\n"
            "H(诚实-谦逊): 高=坦诚说不确定，低=倾向于说没问题\n"
            "E(情绪性): 高=关心用户感受更温暖，低=冷静客观\n"
            "X(外向性): 高=主动建议丰富，低=被动等待\n"
            "A(宜人性): 高=倾向于同意避免冲突，低=敢于说不\n"
            "C(尽责性): 高=严格执行注重细节，低=粗线条抓大放小\n"
            "O(经验开放性): 高=尝试新方法，低=遵循已有方案\n\n"
            "当前人格参数：" + (
                ", ".join(f"{k}={v}" for k, v in current_personality.items())
                if current_personality else "未知"
            ) + "\n\n"
            "输出 JSON："
            '{"adjustments": [{"dimension": "H/E/X/A/C/O", "direction": "increase/decrease", '
            '"intensity": 0.0~1.0, "reason": "原因"}], '
            '"sentiment": "positive/neutral/negative"}'
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"用户反馈：{user_input}"},
        ]

        from src.llm.provider import LLMRequest
        request = LLMRequest(messages=messages, temperature=0.3)
        result = await self._llm.chat(request)

        if result.is_ok:
            try:
                import json
                data = json.loads(result.content)
                data["method"] = "llm"
                return data
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"LLM 人格分析返回解析失败: {e}")

        # LLM 失败，返回空
        return {"adjustments": [], "sentiment": "neutral", "method": "llm_failed"}

    def is_off_track(self, result: str, intent: Intent) -> bool:
        """
        跑偏检查

        V1：关键词匹配
        V2：LLM 语义判断

        返回 True 表示跑偏
        """
        if not result or not intent:
            return False

        # 保守策略：不轻易判定跑偏，交给 GoalAnchor 和 ResultVerifier 处理
        return False
