"""
可交付性评估器（DeliverableValidator）

根据 Intent 定义交付物、验收标准、测试方法，并评估可行性。

设计来源：
- 02_理解层设计.md §五、DeliverableValidator — 可交付性评估

职责：
1. 根据 Intent 定义交付物
2. 定义可量化的验收标准
3. 定义可自动执行的测试方法
4. 评估可行性

设计原则：
- 验收标准必须可量化（不是"代码写得好"，而是"通过 pylint，覆盖率>80%"）
- 测试方法必须可自动执行（不是"用户试试看"，而是"运行 pytest tests/"）
- 可行性必须评估（不能做的要说不能做）
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class DeliverableType(Enum):
    """交付物类型"""
    CODE = "code"
    DOCUMENT = "document"
    REPORT = "report"
    TEXT = "text"
    OTHER = "other"


@dataclass
class AcceptanceCriterion:
    """一条验收标准"""
    description: str                         # 标准描述
    test_method: str                         # 测试方法（可自动执行的命令/脚本）
    is_automated: bool = True                # 是否可以自动测试
    priority: int = 3                        # 优先级 1-5


@dataclass
class DeliverablePlan:
    """可交付性计划"""
    intent_id: str = ""                      # 关联的 Intent ID
    deliverable_type: str = ""               # 交付物类型：代码/文档/报告/...
    deliverable_description: str = ""         # 交付物描述
    acceptance_criteria: list = field(default_factory=list)  # 验收标准列表[AcceptanceCriterion]
    test_command: str = ""                   # 自动测试命令
    required_resources: dict = field(default_factory=dict)   # 所需资源
    estimated_steps: int = 0                 # 预估步骤数
    feasibility: float = 0.0                 # 可行性 0-1
    feasibility_notes: str = ""              # 可行性说明
    id: str = ""                             # 自身 ID


class DeliverableValidator:
    """
    可交付性评估器

    职责：
    1. 根据 Intent 定义交付物
    2. 定义可量化的验收标准
    3. 定义可自动执行的测试方法
    4. 评估可行性

    设计原则：
    - 验收标准必须可量化
    - 测试方法必须可自动执行
    - 可行性必须评估（不能做的要说不能做）
    """

    def __init__(self, llm_fn=None):
        self.llm_fn = llm_fn

    async def evaluate(self, intent) -> DeliverablePlan:
        """
        评估可交付性（核心入口）

        流程：
        1. 判断是否需要可交付性评估（对话类型不需要）
        2. 定义交付物
        3. 定义验收标准
        4. 定义测试方法
        5. 评估可行性
        6. 输出 DeliverablePlan

        Args:
            intent: Intent 对象（来自 UnderstandingEngine.parse()）

        Returns:
            DeliverablePlan: 可交付性计划
        """
        # 对话/问答类型不需要交付物
        intent_type = getattr(intent, 'type', '')
        if intent_type in ('llm_chat', 'conversation', 'question'):
            return DeliverablePlan(
                intent_id=getattr(intent, 'id', '') or getattr(intent, 'content', '')[:20],
                feasibility_notes=f"{intent_type}类型，不需要可交付性评估",
                feasibility=1.0,
            )

        if self.llm_fn:
            plan = await self._evaluate_with_llm(intent)
        else:
            plan = self._evaluate_with_rules(intent)

        plan.intent_id = getattr(intent, 'id', '') or getattr(intent, 'content', '')[:20]

        logger.info(
            f"可交付性评估 [{plan.id}]: "
            f"deliverable={plan.deliverable_type}, "
            f"criteria={len(plan.acceptance_criteria)}, "
            f"feasibility={plan.feasibility:.2f}"
        )
        return plan

    async def _evaluate_with_llm(self, intent) -> DeliverablePlan:
        """用 LLM 评估可交付性"""
        intent_type = getattr(intent, 'type', '')
        content = getattr(intent, 'content', '')

        prompt = f"""分析以下任务，定义交付物和验收标准。

=== 任务 ===
意图类型：{intent_type}
内容：{content}

请输出 JSON：
{{
    "deliverable_type": "交付物类型",
    "deliverable_description": "交付物详细描述",
    "acceptance_criteria": [
        {{
            "description": "标准描述（可量化）",
            "test_method": "测试方法（可自动执行的命令/步骤）",
            "is_automated": true,
            "priority": 1-5
        }}
    ],
    "test_command": "一键测试命令（如：pytest tests/）",
    "required_resources": {{"资源名": "说明"}},
    "estimated_steps": 预估步骤数,
    "feasibility": 0.0-1.0,
    "feasibility_notes": "可行性说明（为什么能/不能做）"
}}

要求：
1. 验收标准必须可量化（不是"代码写得好"，而是具体指标）
2. 测试方法必须可自动执行（不是"用户试试看"，而是具体命令）
3. 如果不可行，feasibility < 0.5，并说明原因"""

        try:
            response = self.llm_fn(prompt)
            data = json.loads(response)

            criteria = [
                AcceptanceCriterion(
                    description=c["description"],
                    test_method=c["test_method"],
                    is_automated=c.get("is_automated", True),
                    priority=c.get("priority", 3),
                )
                for c in data.get("acceptance_criteria", [])
            ]

            return DeliverablePlan(
                deliverable_type=data.get("deliverable_type", ""),
                deliverable_description=data.get("deliverable_description", ""),
                acceptance_criteria=criteria,
                test_command=data.get("test_command", ""),
                required_resources=data.get("required_resources", {}),
                estimated_steps=data.get("estimated_steps", 0),
                feasibility=float(data.get("feasibility", 0.5)),
                feasibility_notes=data.get("feasibility_notes", ""),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"LLM 可交付性评估失败: {e}，降级到规则评估")
            return self._evaluate_with_rules(intent)

    def _evaluate_with_rules(self, intent) -> DeliverablePlan:
        """规则评估（无 LLM 时的降级方案）"""
        intent_type = getattr(intent, 'type', '')
        content = getattr(intent, 'content', '')

        # 开发类任务 → 代码交付物
        dev_types = {'memory_write', 'tool_call', 'subagent_task'}
        if intent_type in dev_types:
            return DeliverablePlan(
                deliverable_type="代码",
                deliverable_description=content or intent_type,
                acceptance_criteria=[
                    AcceptanceCriterion(
                        description="代码能运行",
                        test_method=f"运行相关测试",
                        is_automated=True,
                        priority=5,
                    ),
                ],
                feasibility=0.6,
                feasibility_notes="规则评估，精度有限",
            )

        return DeliverablePlan(
            deliverable_type="文本",
            deliverable_description=content or intent_type,
            acceptance_criteria=[],
            feasibility=0.5,
            feasibility_notes="规则评估，精度有限",
        )
