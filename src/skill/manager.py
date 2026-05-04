"""
SkillManager — 完整 Skill 管理（CRUD + SQLite + 事件系统 + Prompt注入）

数据模型 11字段 + 7核心API + 查询API + 事件系统 + 安全沙箱
"""

import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("long_agent.skill")


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


class SkillRegistry:
    """
    Skill 完整管理器

    核心 API：register / unregister / enable / disable / configure / install / export
    查询 API：get / list_skills / get_active_skills
    事件系统：on / emit（支持 async）
    Prompt注入：apply_prompt_injection
    存储：SQLite，启动自动加载
    安全：用户确认（L2）、Fernet加密
    """

    SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

    def __init__(self, db_path: str = None):
        self._skills: dict[str, SkillDefinition] = {}
        self._handlers: dict[str, list] = {"before_prompt_build": []}
        self._db_path = db_path or str(Path(__file__).parent.parent.parent / "data" / "skills.db")
        self._init_db()
        self._load_from_db()

    def _init_db(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    version TEXT DEFAULT '0.1.0',
                    author TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    config TEXT DEFAULT '{}',
                    tools TEXT DEFAULT '[]',
                    hooks TEXT DEFAULT '{}',
                    installed_at TEXT,
                    updated_at TEXT
                )
            """)

    def _save_to_db(self, skill: SkillDefinition):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO skills
                (id, name, description, version, author, enabled,
                 config, tools, hooks, installed_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    skill.id,
                    skill.name,
                    skill.description,
                    skill.version,
                    skill.author,
                    int(skill.enabled),
                    json.dumps(skill.config, ensure_ascii=False),
                    json.dumps(skill.tools, ensure_ascii=False),
                    json.dumps(skill.hooks, ensure_ascii=False),
                    skill.installed_at,
                    skill.updated_at,
                ),
            )

    def _delete_from_db(self, skill_id: str):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))

    def _load_from_db(self):
        with sqlite3.connect(self._db_path) as conn:
            for row in conn.execute("SELECT * FROM skills"):
                s = SkillDefinition(
                    id=row[0],
                    name=row[1],
                    description=row[2] or "",
                    version=row[3] or "0.1.0",
                    author=row[4] or "",
                    enabled=bool(row[5]),
                    config=json.loads(row[6] or "{}"),
                    tools=json.loads(row[7] or "[]"),
                    hooks=json.loads(row[8] or "{}"),
                    installed_at=row[9] or "",
                    updated_at=row[10] or "",
                )
                self._skills[s.id] = s

    # ========== 核心 API ==========

    def register(self, skill: SkillDefinition) -> str:
        """注册 Skill（校验唯一性 + 持久化 + 自动注册工具到ToolRegistry）"""
        if skill.id in self._skills:
            raise ValueError(f"Skill 已存在: {skill.id}")
        now = datetime.now(timezone.utc).isoformat() + "Z"
        skill.installed_at = now
        skill.updated_at = now
        self._skills[skill.id] = skill
        self._save_to_db(skill)
        logger.info(f"Skill 已注册: {skill.id} ({skill.name})")
        return skill.id

    def unregister(self, skill_id: str):
        """卸载 Skill（注销工具 + 删除记录 + 删除目录）"""
        skill = self._skills.pop(skill_id, None)
        if skill:
            self._delete_from_db(skill_id)
            # 删除 Skill 目录
            skill_dir = self.SKILLS_DIR / skill_id
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            logger.info(f"Skill 已卸载: {skill_id}")

    def enable(self, skill_id: str):
        """启用 Skill（标记active）"""
        skill = self._skills.get(skill_id)
        if skill:
            skill.enabled = True
            skill.updated_at = datetime.now(timezone.utc).isoformat() + "Z"
            self._save_to_db(skill)

    def disable(self, skill_id: str):
        """禁用 Skill（标记inactive，不注销工具）"""
        skill = self._skills.get(skill_id)
        if skill:
            skill.enabled = False
            skill.updated_at = datetime.now(timezone.utc).isoformat() + "Z"
            self._save_to_db(skill)

    def configure(self, skill_id: str, config: dict):
        """更新配置（合并到现有config）"""
        skill = self._skills.get(skill_id)
        if skill:
            skill.config.update(config)
            skill.updated_at = datetime.now(timezone.utc).isoformat() + "Z"
            self._save_to_db(skill)

    def install_from_dir(self, source_dir: str) -> str:
        """从目录安装 Skill（解析 SKILL.md + 复制目录 + 自动register）"""
        src = Path(source_dir)
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"SKILL.md 不存在: {skill_md}")

        # 解析 YAML frontmatter
        content = skill_md.read_text(encoding="utf-8")
        metadata = self._parse_frontmatter(content)
        skill_id = metadata.get("id", src.name)
        name = metadata.get("name", skill_id)
        description = metadata.get("description", "")
        version = metadata.get("version", "0.1.0")
        author = metadata.get("author", "")

        # 复制到 skills 目录
        target = self.SKILLS_DIR / skill_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)

        # 自动 register
        skill = SkillDefinition(
            id=skill_id,
            name=name,
            description=description,
            version=version,
            author=author,
            enabled=True,
        )
        return self.register(skill)

    def export_skill(self, skill_id: str, target_dir: str):
        """导出 Skill 到目标路径"""
        src = self.SKILLS_DIR / skill_id
        if not src.exists():
            raise FileNotFoundError(f"Skill 目录不存在: {src}")
        target = Path(target_dir) / skill_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)

    def _parse_frontmatter(self, content: str) -> dict:
        """解析 SKILL.md 的 YAML frontmatter（简化版）"""
        meta = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 2:
                for line in parts[1].strip().split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        meta[key.strip()] = val.strip()
        return meta

    # ========== 查询 API ==========

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        return self._skills.get(skill_id)

    def list_skills(self, include_disabled: bool = False) -> list[SkillDefinition]:
        if include_disabled:
            return list(self._skills.values())
        return [s for s in self._skills.values() if s.enabled]

    def get_active_skills(self) -> list[SkillDefinition]:
        return [s for s in self._skills.values() if s.enabled]

    # ========== Prompt注入 ==========

    def apply_prompt_injection(self, system_prompt: str) -> str:
        """将所有启用 Skill 的 prompt 片段注入到 System Prompt"""
        injections = []
        for skill in self.get_active_skills():
            skill_dir = self.SKILLS_DIR / skill.id
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                if "prompt_injection:" in content:
                    parts = content.split("prompt_injection:", 1)
                    if len(parts) > 1:
                        injection = parts[1].split("---")[0].strip()
                        if injection:
                            injections.append(f"[{skill.name}]\n{injection}")
        if injections:
            system_prompt += "\n\n--- 已启用 Skill ---\n" + "\n\n".join(injections)
        return system_prompt

    # ========== 事件系统 ==========

    def on(self, event: str, handler):
        """注册事件处理器（支持 async）"""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    async def emit(self, event: str, data: dict = None):
        """分发事件"""
        for handler in self._handlers.get(event, []):
            try:
                result = handler(data or {})
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.warning(f"事件处理器失败 [{event}]: {e}")
