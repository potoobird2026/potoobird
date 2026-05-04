"""
理解层模块

导出：
- Intent: 结构化意图数据类
- ClarificationResult: 追问结果
- UnderstandingEngine: 意图理解引擎
- DeliverablePlan: 可交付性计划
- AcceptanceCriterion: 验收标准
- DeliverableValidator: 可交付性评估器
"""

from src.understanding.engine import (
    ClarificationResult,
    Intent,
    UnderstandingEngine,
)
from src.understanding.deliverable_validator import (
    AcceptanceCriterion,
    DeliverablePlan,
    DeliverableValidator,
)

__all__ = [
    "AcceptanceCriterion",
    "ClarificationResult",
    "DeliverablePlan",
    "DeliverableValidator",
    "Intent",
    "UnderstandingEngine",
]
