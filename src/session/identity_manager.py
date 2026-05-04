"""
IdentityManager — 统一身份管理器

职责：
- 将不同渠道的 user_id 映射到统一的 universal_id
- 支持主动关联（用户验证绑定）
- 支持自动匹配（邮箱/手机号/用户名相似度）

设计文档：DESIGN-V2.md §8.3
"""

import json
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger("long_agent.session.identity_manager")


class IdentityManager:
    """
    统一身份管理器 — 跨渠道身份统一

    映射规则：
    - key = f"{channel}:{user_id}" → universal_id
    - 首次遇到创建新的 universal_id（UUID前12位）
    - 支持主动绑定（用户验证后关联两个渠道）
    - 支持自动匹配（基于邮箱/手机号/用户名相似度）
    """

    def __init__(self, storage_path: str = None):
        """
        Args:
            storage_path: 身份映射存储路径（None 时由用户配置或 LLM 动态确定）
        """
        self._storage_path = storage_path or "./data/identities.json"
        self._identity_map: dict[str, str] = {}  # f"{channel}:{user_id}" -> universal_id
        self._reverse_map: dict[str, set] = {}  # universal_id -> {f"{channel}:{user_id}"}
        self._load()

    def _load(self):
        """从存储加载身份映射"""
        if os.path.exists(self._storage_path):
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._identity_map = data.get("identity_map", {})
                # 重建反向索引
                for key, uid in self._identity_map.items():
                    if uid not in self._reverse_map:
                        self._reverse_map[uid] = set()
                    self._reverse_map[uid].add(key)
                logger.info(f"身份映射加载: {len(self._identity_map)} 条")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"身份映射加载失败: {e}，使用空映射")
                self._identity_map = {}
                self._reverse_map = {}

    def _save(self):
        """持久化身份映射"""
        os.makedirs(os.path.dirname(self._storage_path) or ".", exist_ok=True)
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump({"identity_map": self._identity_map}, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"身份映射保存失败: {e}")

    async def resolve(self, channel: str, channel_user_id: str) -> str:
        """
        解析渠道 user_id → universal_id

        Args:
            channel: 渠道名称（如 "wechat", "telegram", "discord"）
            channel_user_id: 渠道用户 ID

        Returns:
            str: universal_id
        """
        key = f"{channel}:{channel_user_id}"
        if key in self._identity_map:
            return self._identity_map[key]

        # 自动匹配：查找是否有相似身份
        universal_id = self._auto_match(channel, channel_user_id)
        if universal_id:
            logger.info(f"自动匹配身份: {key} → {universal_id}")
        else:
            # 创建新的 universal_id
            universal_id = str(uuid.uuid4())[:12]

        # 建立映射
        self._identity_map[key] = universal_id
        if universal_id not in self._reverse_map:
            self._reverse_map[universal_id] = set()
        self._reverse_map[universal_id].add(key)
        self._save()

        logger.info(f"身份解析: {key} → {universal_id}")
        return universal_id

    def _auto_match(self, channel: str, channel_user_id: str) -> Optional[str]:
        """
        自动匹配：基于同一渠道_user_id是否已在其他渠道出现

        当前实现：精确匹配 user_id（适用于跨平台同ID用户）
        V2 扩展：邮箱/手机号/用户名相似度匹配
        """
        # 查找是否有其他渠道使用了相同的 user_id
        for key, uid in self._identity_map.items():
            _, existing_user_id = key.split(":", 1)
            if existing_user_id == channel_user_id:
                return uid
        return None

    async def bind(self, channel_a: str, user_id_a: str, channel_b: str, user_id_b: str) -> str:
        """
        主动关联：将两个渠道的身份绑定到同一 universal_id

        Args:
            channel_a: 渠道 A
            user_id_a: 渠道 A 用户 ID
            channel_b: 渠道 B
            user_id_b: 渠道 B 用户 ID

        Returns:
            str: 统一的 universal_id

        Raises:
            ValueError: 两个身份已绑定到不同的 universal_id
        """
        key_a = f"{channel_a}:{user_id_a}"
        key_b = f"{channel_b}:{user_id_b}"

        uid_a = self._identity_map.get(key_a)
        uid_b = self._identity_map.get(key_b)

        if uid_a and uid_b and uid_a != uid_b:
            raise ValueError(f"身份冲突：{key_a} → {uid_a}, {key_b} → {uid_b}。请先解绑其中一个。")

        universal_id = uid_a or uid_b or str(uuid.uuid4())[:12]

        self._identity_map[key_a] = universal_id
        self._identity_map[key_b] = universal_id

        if universal_id not in self._reverse_map:
            self._reverse_map[universal_id] = set()
        self._reverse_map[universal_id].add(key_a)
        self._reverse_map[universal_id].add(key_b)

        self._save()
        logger.info(f"身份绑定: {key_a} ↔ {key_b} → {universal_id}")
        return universal_id

    def get_channels(self, universal_id: str) -> list:
        """
        获取 universal_id 绑定的所有渠道

        Args:
            universal_id: 统一用户 ID

        Returns:
            list[str]: 渠道列表
        """
        keys = self._reverse_map.get(universal_id, set())
        return [k for k in keys]

    @property
    def count(self) -> int:
        """universal_id 总数"""
        return len(self._reverse_map)
