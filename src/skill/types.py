"""
Skill 类型定义

包含：
- SkillDefinition 数据类（11字段）
- SkillType 枚举（LOCAL / MCP）
- SkillStatus 枚举（ACTIVE / DISABLED / ERROR）
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SkillType(str, Enum):
    """Skill 来源类型"""
    LOCAL = "LOCAL"
    MCP = "MCP"


class SkillStatus(str, Enum):
    """Skill 运行状态"""
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


@dataclass
class SkillDefinition:
    """Skill 完整数据模型（11字段）"""

    id: str = ""
    name: str = ""
    description: str = ""
    version: str = "0.1.0"
    author: str = ""
    enabled: bool = True
    config: dict = field(default_factory=dict)
    tools: list = field(default_factory=list)
    hooks: dict = field(default_factory=dict)
    installed_at: str = ""
    updated_at: str = ""
