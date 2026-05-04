"""
PromptManager — 提示词管理器

职责：
- 提示词模板管理（CRUD）
- 动态提示词组装（人格+记忆+标准+用户输入）
- A/B测试支持（多版本提示词）
- 提示词版本控制

设计文档：DESIGN-V2.md §11 LLM管理

科学依据：
- 提示词工程最佳实践（分隔符、示例、角色设定）
- 上下文窗口预算分配（动态计算各部分token占比）
"""

import logging
import random
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("long_agent.llm.prompt_manager")


@dataclass
class PromptTemplate:
    """提示词模板"""

    name: str
    template: str
    version: str = "1.0"
    description: str = ""
    tags: list = field(default_factory=list)


class PromptManager:
    """
    提示词管理器

    职责：
    - 管理提示词模板库
    - 根据上下文动态组装system prompt
    - 支持多版本和A/B测试
    """

    def __init__(self):
        self._templates: dict[str, PromptTemplate] = {}
        self._register_default_templates()
        logger.info(f"PromptManager 初始化完成，默认模板数: {len(self._templates)}")

    def _register_default_templates(self):
        """注册默认提示词模板"""
        self._templates["system_base"] = PromptTemplate(
            name="system_base",
            template=("你是一个AI助手。\n当前时间: {current_time}\n用户ID: {user_id}\n"),
            version="1.0",
            description="基础系统提示词",
        )

        self._templates["with_personality"] = PromptTemplate(
            name="with_personality",
            template=(
                "你是一个AI助手，以下是你的性格参数（HEXACO模型，0-100）：\n"
                "H(诚实-谦逊)={H}, E(情绪性)={E}, X(外向性)={X}, "
                "A(宜人性)={A}, C(尽责性)={C}, O(经验开放性)={O}\n"
                "请根据这些参数调整你的回复风格。\n"
            ),
            version="1.0",
            description="含人格参数的提示词",
        )

        self._templates["intent_analysis"] = PromptTemplate(
            name="intent_analysis",
            template=(
                "你是一个意图分析助手。分析用户输入，理解其真实意图。\n"
                "相关记忆：\n{relevant_memories}\n\n"
                "当前标准：\n{standards}\n\n"
                "输出JSON格式："
                '{"type": "memory_write|memory_read|memory_search|llm_chat|unknown", '
                '"confidence": 0.0-1.0, '
                '"requires_approval": true|false}'
            ),
            version="1.0",
            description="意图分析提示词",
        )

        self._templates["with_standards"] = PromptTemplate(
            name="with_standards",
            template=("你需要遵守以下开发标准：\n{standards}\n在回复中始终遵循这些标准。\n"),
            version="1.0",
            description="含标准的提示词",
        )

    def get_template(self, name: str) -> Optional[PromptTemplate]:
        """获取模板"""
        return self._templates.get(name)

    def register_template(self, template: PromptTemplate) -> None:
        """注册新模板"""
        self._templates[template.name] = template
        logger.info(f"模板注册: {template.name} v{template.version}")

    def build_system_prompt(
        self,
        personality: dict = None,
        memories: list = None,
        standards: list = None,
        user_id: str = "default",
    ) -> str:
        """
        动态组装system prompt

        Args:
            personality: HEXACO人格参数 {"H": 50, "E": 50, ...}
            memories: 相关记忆列表
            standards: 相关标准列表
            user_id: 用户ID

        Returns:
            str: 组装好的system prompt
        """
        from datetime import datetime

        parts = []

        # 1. 基础部分
        base = self._templates.get("system_base")
        if base:
            parts.append(
                base.template.format(
                    current_time=datetime.utcnow().isoformat() + "Z",
                    user_id=user_id,
                )
            )

        # 2. 人格部分
        if personality:
            p = self._templates.get("with_personality")
            if p:
                parts.append(
                    p.template.format(
                        H=personality.get("H", 50),
                        E=personality.get("E", 50),
                        X=personality.get("X", 50),
                        A=personality.get("A", 50),
                        C=personality.get("C", 50),
                        O=personality.get("O", 50),
                    )
                )

        # 3. 记忆部分
        if memories:
            mem_lines = "\n".join(f"- {m}" for m in memories[:5])
            parts.append(f"相关记忆：\n{mem_lines}\n")

        # 4. 标准部分
        if standards:
            std_lines = "\n".join(f"- {s}" for s in standards[:10])
            std_template = self._templates.get("with_standards")
            if std_template:
                parts.append(std_template.template.format(standards=std_lines))
            else:
                parts.append(f"开发标准：\n{std_lines}\n")

        return "\n".join(parts)

    def list_templates(self) -> list[str]:
        """列出所有模板名称"""
        return list(self._templates.keys())


# ========== V2 补全：render_prompt + record_feedback + Thompson Sampling ==========


@dataclass
class PromptVariant:
    """提示词变体（A/B 测试用）"""

    name: str = ""
    template: str = ""
    variant: str = "default"  # "default" / "variant_a" / "variant_b" / ...
    success_count: int = 0
    total_count: int = 0


class PromptManagerV2:
    """
    提示词管理器 V2 — A/B 测试 + Thompson Sampling

    设计原则：
    - Prompt 模板由 LLM 动态生成，不硬编码
    - 质量评分学习率由评分波动性动态调整，不写死
    - Thompson Sampling 权重由用户反馈动态调整

    设计文档：DESIGN-V2.md §11.3
    """

    def __init__(self):
        self._templates: dict[str, list[PromptVariant]] = {}
        # Thompson Sampling 权重不写死，由用户反馈动态调整
        # key: task_type, value: {variant_name: (alpha, beta)}
        self._ts_weights: dict[str, dict[str, tuple[float, float]]] = {}
        logger.info("PromptManagerV2 初始化完成")

    def register_template(self, task_type: str, template: str, variant: str = "default"):
        """
        注册提示词模板变体

        Args:
            task_type: 任务类型
            template: 模板内容
            variant: 变体名称
        """
        if task_type not in self._templates:
            self._templates[task_type] = []
        self._templates[task_type].append(
            PromptVariant(name=task_type, template=template, variant=variant)
        )
        # 初始化 Thompson Sampling 权重
        if task_type not in self._ts_weights:
            self._ts_weights[task_type] = {}
        if variant not in self._ts_weights[task_type]:
            self._ts_weights[task_type][variant] = (1.0, 1.0)  # Beta(1,1) 均匀先验
        logger.info(f"模板注册: task_type={task_type}, variant={variant}")

    def render_prompt(self, task_type: str, variables: dict) -> str:
        """
        渲染 Prompt 模板（Thompson Sampling 选择最优变体）

        使用 Thompson Sampling 从多个变体中选择最优版本：
        1. 对每个变体，从 Beta(alpha, beta) 采样
        2. 选择采样值最高的变体
        3. 用 variables 填充模板

        Args:
            task_type: 任务类型
            variables: 模板变量

        Returns:
            str: 渲染后的 prompt
        """
        variants = self._templates.get(task_type, [])
        if not variants:
            logger.warning(f"任务类型 {task_type} 无模板，返回空 prompt")
            return ""

        if len(variants) == 1:
            selected = variants[0]
        else:
            # Thompson Sampling 选择
            weights = self._ts_weights.get(task_type, {})
            best_variant = None
            best_sample = -1.0

            for v in variants:
                alpha, beta = weights.get(v.variant, (1.0, 1.0))
                # 从 Beta 分布采样
                sample = random.betavariate(alpha, beta)
                if sample > best_sample:
                    best_sample = sample
                    best_variant = v

            selected = best_variant or variants[0]

        # 渲染模板
        try:
            rendered = selected.template.format(**variables)
        except KeyError as e:
            logger.warning(f"模板变量缺失: {e}")
            rendered = selected.template

        logger.debug(f"Prompt 渲染: task_type={task_type}, variant={selected.variant}")
        return rendered

    def record_feedback(self, task_type: str, variant: str, quality: float):
        """
        记录质量反馈（用于 Thompson Sampling 更新）

        Args:
            task_type: 任务类型
            variant: 变体名称
            quality: 质量评分 [0, 1]
        """
        if task_type not in self._ts_weights:
            self._ts_weights[task_type] = {}

        alpha, beta = self._ts_weights[task_type].get(variant, (1.0, 1.0))

        # Beta 分布更新：quality=1 → alpha+1, quality=0 → beta+1
        # 支持 [0, 1] 连续值
        alpha += quality
        beta += 1.0 - quality

        self._ts_weights[task_type][variant] = (alpha, beta)

        # 更新变体计数
        variants = self._templates.get(task_type, [])
        for v in variants:
            if v.variant == variant:
                v.total_count += 1
                if quality >= 0.5:
                    v.success_count += 1
                break

        logger.info(
            f"反馈记录: task_type={task_type}, variant={variant}, "
            f"quality={quality:.2f}, Beta=({alpha:.1f}, {beta:.1f})"
        )
