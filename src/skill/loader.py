"""
SkillLoader — Skill 目录加载器

从指定目录扫描并加载 Skill 模块：
- 遍历子目录
- 检查 SKILL.md 存在
- 动态 import 模块
- 创建 SkillDefinition 实例
- 注册到 SkillRegistry
"""

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Optional

from src.skill.registry import SkillRegistry
from src.skill.types import SkillDefinition

logger = logging.getLogger("long_agent.skill")


class SkillLoader:
    """Skill 目录加载器"""

    def __init__(self, registry: Optional[SkillRegistry] = None):
        self.registry = registry or SkillRegistry()

    def load_from_dir(self, source_dir: str) -> list[SkillDefinition]:
        """
        从目录加载所有 Skill

        每个子目录视为一个 Skill，需包含 SKILL.md。
        可选包含 skill_module.py，其中有 create_skill() 工厂函数。

        Args:
            source_dir: Skill 目录路径（子目录 = 单个 Skill）

        Returns:
            加载成功的 SkillDefinition 列表
        """
        src = Path(source_dir)
        if not src.exists():
            logger.warning("Skill 源目录不存在: %s", source_dir)
            return []
        if not src.is_dir():
            logger.warning("Skill 源路径不是目录: %s", source_dir)
            return []

        loaded: list[SkillDefinition] = []

        for skill_dir in sorted(src.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name.startswith("_") or skill_dir.name.startswith("."):
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                logger.debug("跳过（无 SKILL.md）: %s", skill_dir.name)
                continue

            try:
                skill = self._load_single_skill(skill_dir)
                if skill:
                    loaded.append(skill)
            except Exception as e:
                logger.error("加载 Skill 失败 %s: %s", skill_dir.name, e)

        logger.info("从 %s 加载 %d 个 Skill", source_dir, len(loaded))
        return loaded

    def _load_single_skill(self, skill_dir: Path) -> Optional[SkillDefinition]:
        """加载单个 Skill 目录"""
        skill_id = skill_dir.name
        skill_md = skill_dir / "SKILL.md"

        # 解析 meta
        meta = SkillRegistry._parse_skill_meta(skill_md)

        # 尝试 import 模块（可选）
        module = self._import_skill_module(skill_dir)

        # 尝试从模块获取 SkillDefinition
        if module and hasattr(module, "create_skill"):
            try:
                skill = module.create_skill()
                if isinstance(skill, SkillDefinition):
                    self.registry.register(skill)
                    logger.info("通过模块工厂加载 Skill: %s", skill.id)
                    return skill
            except Exception as e:
                logger.warning("模块工厂加载失败 %s: %s", skill_id, e)

        # Fallback：从 meta 构建
        skill = SkillDefinition(
            id=skill_id,
            name=meta.get("name", skill_id),
            description=meta.get("description", ""),
            version=meta.get("version", "0.1.0"),
            author=meta.get("author", ""),
            enabled=True,
        )
        self.registry.register(skill)
        logger.info("通过 meta 加载 Skill: %s", skill.id)
        return skill

    @staticmethod
    def _import_skill_module(skill_dir: Path):
        """
        动态 import Skill 模块

        查找 skill_module.py 或 __init__.py
        """
        module_file = skill_dir / "skill_module.py"
        if not module_file.exists():
            module_file = skill_dir / "__init__.py"
        if not module_file.exists():
            return None

        module_name = f"skill_{skill_dir.name}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        except Exception as e:
            logger.warning("模块 import 失败 %s: %s", skill_dir.name, e)
        return None
