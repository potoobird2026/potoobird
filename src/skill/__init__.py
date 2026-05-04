"""
Skill 子包

分层结构：
- types.py    : 类型定义（SkillDefinition, SkillType, SkillStatus）
- registry.py : 核心注册表（CRUD + SQLite + 事件 + Prompt注入）
- loader.py   : 目录加载器（扫描 + import + 注册）
- sandbox.py  : 安全沙箱（超时执行 + 结果封装）
"""

from src.skill.loader import SkillLoader
from src.skill.registry import SkillRegistry
from src.skill.sandbox import SandboxResult, run_in_executor
from src.skill.types import SkillDefinition, SkillStatus, SkillType

__all__ = [
    "SkillDefinition",
    "SkillStatus",
    "SkillType",
    "SkillRegistry",
    "SkillLoader",
    "SandboxResult",
    "run_in_executor",
]
