"""
MCP 凭据加密工具

使用 Fernet 对称加密保护 headers 中的认证信息。
密钥从环境变量 MCP_ENCRYPTION_KEY 读取，
若未设置则自动生成并缓存到实例中。
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("long_agent.mcp.crypto")

try:
    from cryptography.fernet import Fernet

    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False
    logger.warning("cryptography 未安装，MCP 凭据将以明文存储")


class McpCrypto:
    """
    MCP 凭据加解密

    加密范围：
    - headers 中以 "Authorization"、"X-API-Key"、"X-Token" 等开头的值
    - 其他包含 "key"、"token"、"secret"、"password" 的 header 值

    使用方式：
        crypto = McpCrypto()
        encrypted_headers = crypto.encrypt_headers(headers)
        decrypted_headers = crypto.decrypt_headers(encrypted_headers)
    """

    # 需要加密的 header 名称模式
    SENSITIVE_KEYS = re.compile(
        r"^(authorization|x-api-key|x-token|x-secret|"
        r".*key.*|.*token.*|.*secret.*|.*password.*)$",
        re.IGNORECASE,
    )

    _MARKER = "__ENC__:"

    def __init__(self, key: str | None = None):
        self._fernet: Fernet | None = None

        if not _HAS_FERNET:
            return

        # 获取密钥
        raw_key = key or os.environ.get("MCP_ENCRYPTION_KEY")
        if raw_key:
            try:
                self._fernet = Fernet(raw_key.encode() if isinstance(raw_key, str) else raw_key)
            except Exception:
                logger.warning("提供的 MCP_ENCRYPTION_KEY 无效，将生成新密钥")
                self._fernet = None

        if self._fernet is None:
            # 自动生成密钥
            if _HAS_FERNET:
                fernet_key = Fernet.generate_key()
                self._fernet = Fernet(fernet_key)
                logger.info(
                    f"已自动生成 MCP 加密密钥，"
                    f"请设置环境变量 MCP_ENCRYPTION_KEY={fernet_key.decode()!r} 以持久化"
                )

    @property
    def is_available(self) -> bool:
        return _HAS_FERNET and self._fernet is not None

    def encrypt_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """
        加密 headers 中的敏感字段。
        非敏感字段原样保留。
        """
        if not self.is_available:
            return dict(headers)

        result = {}
        for k, v in headers.items():
            if self.SENSITIVE_KEYS.match(k):
                try:
                    encrypted = self._fernet.encrypt(v.encode()).decode()
                    result[k] = f"{self._MARKER}{encrypted}"
                except Exception:
                    result[k] = v
            else:
                result[k] = v
        return result

    def decrypt_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """
        解密 headers 中的加密字段。
        未加密的字段原样保留。
        """
        if not self.is_available:
            return dict(headers)

        result = {}
        for k, v in headers.items():
            if v.startswith(self._MARKER):
                try:
                    encrypted = v[len(self._MARKER) :]
                    decrypted = self._fernet.decrypt(encrypted.encode()).decode()
                    result[k] = decrypted
                except Exception:
                    result[k] = v
            else:
                result[k] = v
        return result

    def encrypt_value(self, value: str) -> str:
        """加密单个值"""
        if not self.is_available:
            return value
        return f"{self._MARKER}{self._fernet.encrypt(value.encode()).decode()}"

    def decrypt_value(self, value: str) -> str:
        """解密单个值"""
        if not self.is_available:
            return value
        if value.startswith(self._MARKER):
            try:
                return self._fernet.decrypt(value[len(self._MARKER) :].encode()).decode()
            except Exception:
                return value
        return value
