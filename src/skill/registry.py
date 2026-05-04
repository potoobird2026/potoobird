"""
SkillRegistry — Skill 注册表（CRUD + SQLite + 事件系统 + Prompt注入）

核心 API：register / unregister / enable / disable / configure / install / export
查询 API：get / list_skills / get_active_skills
事件系统：on / emit（支持 async）
Prompt注入：apply_prompt_injection
存储：SQLite WAL 模式，长连接复用
"""

import asyncio
import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.skill.types import SkillDefinition, SkillStatus

logger = logging.getLogger("long_agent.skill")

# ── SQL 常量 ──────────────────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
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
"""

_INSERT_OR_REPLACE_SQL = """
    INSERT OR REPLACE INTO skills
    (id, name, description, version, author, enabled,
     config, tools, hooks, installed_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
"""

_DELETE_BY_ID_SQL = "DELETE FROM skills WHERE id = ?"

_UPDATE_ENABLED_SQL = "UPDATE skills SET enabled = ?, updated_at = ? WHERE id = ?"

_UPDATE_CONFIG_SQL = "UPDATE skills SET config = ?, updated_at = ? WHERE id = ?"

_SELECT_BY_ID_SQL = "SELECT * FROM skills WHERE id = ?"

_SELECT_ALL_SQL = "SELECT * FROM skills ORDER BY installed_at DESC"

_SELECT_ACTIVE_SQL = "SELECT * FROM skills WHERE enabled = 1 ORDER BY installed_at DESC"


class SkillRegistry:
    """
    Skill 完整管理器

    - SQLite WAL 模式，长连接复用
    - 启动自动从 DB 加载
    - 支持事件注册 / 异步 emit
    - 支持 Prompt 注入
    """

    SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

    def __init__(self, db_path: str = None):
        self._skills: dict[str, SkillDefinition] = {}
        self._handlers: dict[str, list] = {"before_prompt_build": []}
        self._db_path = db_path or str(
            Path(__file__).parent.parent.parent / "data" / "skills.db"
        )
        # 长连接复用：__init__ 创建，不每次操作新建
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL 模式：提升并发读性能
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()
        self._load_from_db()

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def close(self):
        """关闭数据库连接"""
        if hasattr(self, "_conn") and self._conn:
            try:
                self._conn.close()
            except Exception:
                pass

    def __del__(self):
        self.close()

    # ── DB 加载/保存 ───────────────────────────────────────────────────────────

    def _row_to_definition(self, row: sqlite3.Row) -> SkillDefinition:
        return SkillDefinition(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            version=row["version"],
            author=row["author"],
            enabled=bool(row["enabled"]),
            config=json.loads(row["config"]),
            tools=json.loads(row["tools"]),
            hooks=json.loads(row["hooks"]),
            installed_at=row["installed_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    def _load_from_db(self):
        """启动时从 SQLite 加载所有 skill"""
        cursor = self._conn.execute(_SELECT_ALL_SQL)
        rows = cursor.fetchall()
        for row in rows:
            skill = self._row_to_definition(row)
            self._skills[skill.id] = skill
        logger.info("从 DB 加载 %d 个 Skill", len(self._skills))

    def _save_to_db(self, skill: SkillDefinition):
        """持久化单个 skill（使用长连接）"""
        self._conn.execute(
            _INSERT_OR_REPLACE_SQL,
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
        self._conn.commit()

    def _delete_from_db(self, skill_id: str):
        """从 DB 删除 skill（使用长连接）"""
        self._conn.execute(_DELETE_BY_ID_SQL, (skill_id,))
        self._conn.commit()

    def _update_enabled_db(self, skill_id: str, enabled: bool):
        """更新 enabled 字段（使用长连接）"""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(_UPDATE_ENABLED_SQL, (int(enabled), now, skill_id))
        self._conn.commit()

    def _update_config_db(self, skill_id: str, config: dict):
        """更新 config 字段（使用长连接）"""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            _UPDATE_CONFIG_SQL,
            (json.dumps(config, ensure_ascii=False), now, skill_id),
        )
        self._conn.commit()

    # ── 核心 CRUD API ──────────────────────────────────────────────────────────

    def register(self, skill: SkillDefinition) -> bool:
        """注册新 Skill（幂等，同名覆盖）"""
        now = datetime.now(timezone.utc).isoformat()
        skill.installed_at = skill.installed_at or now
        skill.updated_at = now
        self._save_to_db(skill)
        self._skills[skill.id] = skill
        logger.info("注册 Skill: %s (%s)", skill.id, skill.name)
        self.emit("skill_registered", skill)
        return True

    def unregister(self, skill_id: str) -> bool:
        """注销 Skill"""
        if skill_id not in self._skills:
            logger.warning("注销失败，Skill 不存在: %s", skill_id)
            return False
        skill = self._skills.pop(skill_id)
        self._delete_from_db(skill_id)
        logger.info("注销 Skill: %s", skill_id)
        self.emit("skill_unregistered", skill)
        return True

    def enable(self, skill_id: str) -> bool:
        """启用 Skill"""
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        skill.enabled = True
        skill.updated_at = datetime.now(timezone.utc).isoformat()
        self._update_enabled_db(skill_id, True)
        self.emit("skill_enabled", skill)
        return True

    def disable(self, skill_id: str) -> bool:
        """禁用 Skill"""
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        skill.enabled = False
        skill.updated_at = datetime.now(timezone.utc).isoformat()
        self._update_enabled_db(skill_id, False)
        self.emit("skill_disabled", skill)
        return True

    def configure(self, skill_id: str, config: dict) -> bool:
        """更新 Skill 配置（合并）"""
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        skill.config.update(config)
        skill.updated_at = datetime.now(timezone.utc).isoformat()
        self._update_config_db(skill_id, skill.config)
        self.emit("skill_configured", skill)
        return True

    def install(self, source_dir: str, confirm_cb=None) -> Optional[SkillDefinition]:
        """
        从目录安装 Skill
        - 检查 SKILL.md 存在
        - 用户确认（confirm_cb）
        - 复制到 skills/ 目录
        - 注册到 DB
        """
        src = Path(source_dir)
        if not (src / "SKILL.md").exists():
            logger.error("安装失败：%s 中无 SKILL.md", source_dir)
            return None

        # 读取 meta
        meta = self._parse_skill_meta(src / "SKILL.md")
        skill_id = meta.get("id", src.name)

        # 用户确认
        if confirm_cb and not confirm_cb(skill_id, meta):
            logger.info("用户取消安装: %s", skill_id)
            return None

        # 复制到 skills 目录
        dst = self.SKILLS_DIR / skill_id
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

        # 构建 definition
        skill = SkillDefinition(
            id=skill_id,
            name=meta.get("name", skill_id),
            description=meta.get("description", ""),
            version=meta.get("version", "0.1.0"),
            author=meta.get("author", ""),
            enabled=True,
            config=meta.get("config", {}),
            tools=meta.get("tools", []),
            hooks=meta.get("hooks", {}),
        )
        self.register(skill)
        return skill

    def export(self, skill_id: str, output_dir: str) -> bool:
        """导出 Skill 到目录"""
        skill = self._skills.get(skill_id)
        if not skill:
            return False
        src = self.SKILLS_DIR / skill_id
        if not src.exists():
            logger.error("导出失败：Skill 目录不存在 %s", src)
            return False
        dst = Path(output_dir) / skill_id
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        logger.info("导出 Skill %s → %s", skill_id, dst)
        return True

    # ── 查询 API ───────────────────────────────────────────────────────────────

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        """按 ID 获取 Skill"""
        return self._skills.get(skill_id)

    def list_skills(self) -> list[SkillDefinition]:
        """列出所有 Skill"""
        return list(self._skills.values())

    def get_active_skills(self) -> list[SkillDefinition]:
        """获取所有启用的 Skill"""
        return [s for s in self._skills.values() if s.enabled]

    def get_skills_by_status(self, status: SkillStatus) -> list[SkillDefinition]:
        """按状态过滤 Skill"""
        if status == SkillStatus.ACTIVE:
            return self.get_active_skills()
        elif status == SkillStatus.DISABLED:
            return [s for s in self._skills.values() if not s.enabled]
        return []

    # ── 事件系统 ───────────────────────────────────────────────────────────────

    def on(self, event: str, handler):
        """注册事件处理器"""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    def emit(self, event: str, data=None):
        """触发事件（同步 + 异步处理器）"""
        handlers = self._handlers.get(event, [])
        for handler in handlers:
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    # 异步处理器：创建任务执行
                    asyncio.ensure_future(result)
            except Exception as e:
                logger.error("事件处理异常 %s: %s", event, e)

    # ── Prompt 注入 ────────────────────────────────────────────────────────────

    def apply_prompt_injection(self, prompt: str) -> str:
        """将活跃 Skill 信息注入 Prompt"""
        active = self.get_active_skills()
        if not active:
            return prompt

        injection_parts = []
        for skill in active:
            if skill.hooks.get("prompt_injection"):
                injection_parts.append(f"[Skill:{skill.name}] {skill.description}")

        if injection_parts:
            injection_text = "\n".join(injection_parts)
            # 注入到 prompt 末尾
            prompt = f"{prompt}\n\n--- Active Skills ---\n{injection_text}"

        # 触发 before_prompt_build 事件
        self.emit("before_prompt_build", prompt)
        return prompt

    # ── 工具方法 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_skill_meta(skill_md_path: Path) -> dict:
        """从 SKILL.md 解析 meta 信息（简单 frontmatter 解析）"""
        meta = {}
        if not skill_md_path.exists():
            return meta
        content = skill_md_path.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
        return meta

    def __repr__(self):
        return f"<SkillRegistry skills={len(self._skills)} active={len(self.get_active_skills())}>"
