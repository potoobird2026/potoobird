"""
单元测试 — 配置模块 (src/config/settings.py)

覆盖：
- Settings 默认值
- 环境变量加载
- Fernet 加密/解密
- 字段验证
"""

import os
from unittest.mock import patch

import pytest


class TestFernetEncryption:
    """测试 Fernet 加密/解密"""

    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        """加密后解密得到原值"""
        from src.config.settings import _decrypt, _encrypt, _get_or_create_key

        key_file = str(tmp_path / "data" / ".fernet_key")
        key = _get_or_create_key(key_file)
        assert key is not None
        assert len(key) > 0

        plaintext = "my-secret-api-key"
        encrypted = _encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = _decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_empty_string(self):
        """空字符串加密返回空"""
        from src.config.settings import _decrypt, _encrypt
        assert _encrypt("") == ""
        assert _decrypt("") == ""

    def test_key_persistence(self, tmp_path):
        """密钥文件存在时复用"""
        from src.config.settings import _get_or_create_key

        key_file = str(tmp_path / ".fernet_key")
        key1 = _get_or_create_key(key_file)
        key2 = _get_or_create_key(key_file)
        assert key1 == key2

    def test_key_creates_parent_dirs(self, tmp_path):
        """密钥文件创建时自动创建父目录"""
        from src.config.settings import _get_or_create_key

        key_file = str(tmp_path / "a" / "b" / ".fernet_key")
        key = _get_or_create_key(key_file)
        assert key is not None
        assert os.path.exists(key_file)


class TestSettingsDefaults:
    """测试 Settings 默认值"""

    def test_default_values(self):
        """Settings 实例使用默认值"""
        from src.config.settings import Settings

        with patch.dict(os.environ, {}, clear=True):
            s = Settings()
            assert s.llm_provider == "openai"
            assert s.openai_model == "gpt-4o"
            assert s.llm_timeout == 30
            assert s.llm_max_retries == 3
            assert s.database_path == "data/memory.db"
            assert s.data_dir == "data"
            assert s.backup_dir == "data/backups"
            assert s.backup_keep == 3
            assert s.log_level == "INFO"
            assert s.log_file == "logs/agent.log"
            assert s.log_json_format is False
            assert s.metrics_enabled is True
            assert s.metrics_port == 8001

    def test_env_override(self):
        """环境变量覆盖默认值"""
        from src.config.settings import Settings

        with patch.dict(os.environ, {
            "LONG_AGENT_LLM_PROVIDER": "ollama",
            "LONG_AGENT_OPENAI_MODEL": "gpt-4",
            "LONG_AGENT_LOG_LEVEL": "DEBUG",
            "LONG_AGENT_DATABASE_PATH": "custom/db.sqlite",
        }, clear=True):
            s = Settings()
            assert s.llm_provider == "ollama"
            assert s.openai_model == "gpt-4"
            assert s.log_level == "DEBUG"
            assert s.database_path == "custom/db.sqlite"

    def test_log_level_choices(self):
        """日志级别合法值"""
        from src.config.settings import Settings

        with patch.dict(os.environ, {"LONG_AGENT_LOG_LEVEL": "WARNING"}, clear=True):
            s = Settings()
            assert s.log_level == "WARNING"


class TestSettingsValidation:
    """测试 Settings 字段验证"""

    def test_llm_timeout_range(self):
        """llm_timeout 必须在 5-120 之间"""
        from pydantic import ValidationError

        from src.config.settings import Settings

        with patch.dict(os.environ, {"LONG_AGENT_LLM_TIMEOUT": "200"}, clear=True):
            with pytest.raises(ValidationError):
                Settings()

    def test_backup_keep_range(self):
        """backup_keep 必须在 1-10 之间"""
        from pydantic import ValidationError

        from src.config.settings import Settings

        with patch.dict(os.environ, {"LONG_AGENT_BACKUP_KEEP": "20"}, clear=True):
            with pytest.raises(ValidationError):
                Settings()
