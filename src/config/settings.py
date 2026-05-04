"""
应用配置

加载优先级（高→低）：环境变量 > .env > 默认值
API Key 使用 Fernet 加密存储（DESIGN.md 十五、安全设计）
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger("long_agent.config")

# ---- Fernet 加密（API Key 安全存储） ----


def _get_or_create_key(key_file: str = "data/.fernet_key") -> bytes:
    """获取或创建 Fernet 密钥"""
    key_path = Path(key_file)
    if key_path.exists():
        return key_path.read_bytes()
    # 生成新密钥
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    # 设置文件权限（仅当前用户可读写）
    import platform

    if platform.system() in ("Linux", "Darwin"):
        os.chmod(key_path, 0o600)
    elif platform.system() == "Windows":
        import subprocess

        subprocess.run(["icacls", str(key_path), "/inheritance:r", "/Q"], capture_output=True)
        subprocess.run(
            ["icacls", str(key_path), "/grant", f"{os.getlogin()}:F", "/Q"],
            capture_output=True,
        )
    return key


def _encrypt(value: str) -> str:
    """加密字符串"""
    if not value:
        return ""
    from cryptography.fernet import Fernet

    key = _get_or_create_key()
    return Fernet(key).encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    """解密字符串"""
    if not value:
        return ""
    from cryptography.fernet import Fernet

    key = _get_or_create_key()
    return Fernet(key).decrypt(value.encode()).decode()


# ---- 配置类 ----

try:
    from pydantic import Field, field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            env_prefix="LONG_AGENT_",
        )

        # === LLM ===
        llm_provider: str = Field(default="openai")
        openai_api_key_encrypted: str = Field(
            default="", alias="LONG_AGENT_OPENAI_API_KEY_ENCRYPTED"
        )
        openai_model: str = Field(default="gpt-4o")
        llm_timeout: int = Field(default=30, ge=5, le=120)
        llm_max_retries: int = Field(default=3, ge=0, le=10)

        # === 数据库 ===
        database_path: str = Field(default="data/memory.db")

        # === 数据 ===
        data_dir: str = Field(default="data")
        backup_dir: str = Field(default="data/backups")
        backup_keep: int = Field(default=3, ge=1, le=10)

        # === 日志 ===
        log_level: str = Field(default="INFO")
        log_file: str = Field(default="logs/agent.log")
        log_json_format: bool = Field(default=False)  # V2：JSON 格式日志（便于 Grafana Loki 采集）

        # === 可观测性（V2） ===
        metrics_enabled: bool = Field(default=True)
        metrics_port: int = Field(default=8001, ge=1024, le=65535)
        metrics_path: str = Field(default="/metrics")
        health_enabled: bool = Field(default=True)
        observability_host: str = Field(default="127.0.0.1")

        # === 后台任务 ===
        backup_interval_hours: int = Field(default=24, ge=1, le=168)
        snapshot_cleanup_days: int = Field(default=7, ge=1)
        vacuum_interval_days: int = Field(default=30, ge=1)

        @field_validator("openai_model")
        @classmethod
        def validate_model(cls, v):
            # 不再限制模型列表，任何模型名称都允许
            # 模型可用性由 LLM Provider 在运行时验证
            return v

        @field_validator("log_level")
        @classmethod
        def validate_log_level(cls, v):
            allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
            if v.upper() not in allowed:
                raise ValueError(f"log_level 必须是 {allowed} 之一")
            return v.upper()

        # === 解密属性 ===

        @property
        def openai_api_key(self) -> str:
            """自动解密的 API Key"""
            # 优先读环境变量明文（开发用）
            plain = os.getenv("LONG_AGENT_OPENAI_API_KEY", "")
            if plain:
                return plain
            # 读加密存储
            if self.openai_api_key_encrypted:
                try:
                    return _decrypt(self.openai_api_key_encrypted)
                except Exception as e:
                    logger.error(f"API Key 解密失败: {e}，请检查 .fernet_key 文件")
                    return ""
            return ""

except ImportError:
    logger.warning("pydantic_settings 未安装，使用降级配置")

    class Settings:
        def __init__(self):
            self.llm_provider = os.getenv("LONG_AGENT_LLM_PROVIDER", "openai")
            self._openai_api_key = os.getenv("LONG_AGENT_OPENAI_API_KEY", "")
            self.openai_model = os.getenv("LONG_AGENT_OPENAI_MODEL", "gpt-4o")
            self.llm_timeout = int(os.getenv("LONG_AGENT_LLM_TIMEOUT", "30"))
            self.llm_max_retries = int(os.getenv("LONG_AGENT_LLM_MAX_RETRIES", "3"))
            self.database_path = os.getenv("LONG_AGENT_DATABASE_PATH", "data/memory.db")
            self.data_dir = os.getenv("LONG_AGENT_DATA_DIR", "data")
            self.backup_dir = os.getenv("LONG_AGENT_BACKUP_DIR", "data/backups")
            self.backup_keep = int(os.getenv("LONG_AGENT_BACKUP_KEEP", "3"))
            self.log_level = os.getenv("LONG_AGENT_LOG_LEVEL", "INFO")
            self.log_file = os.getenv("LONG_AGENT_LOG_FILE", "logs/agent.log")
            # V2 可观测性
            self.log_json_format = (
                os.getenv("LONG_AGENT_LOG_JSON_FORMAT", "false").lower() == "true"
            )
            self.metrics_enabled = os.getenv("LONG_AGENT_METRICS_ENABLED", "true").lower() == "true"
            self.metrics_port = int(os.getenv("LONG_AGENT_METRICS_PORT", "8001"))
            self.metrics_path = os.getenv("LONG_AGENT_METRICS_PATH", "/metrics")
            self.health_enabled = os.getenv("LONG_AGENT_HEALTH_ENABLED", "true").lower() == "true"
            self.observability_host = os.getenv("LONG_AGENT_OBSERVABILITY_HOST", "127.0.0.1")
            self.backup_interval_hours = int(os.getenv("LONG_AGENT_BACKUP_INTERVAL_HOURS", "24"))
            self.snapshot_cleanup_days = int(os.getenv("LONG_AGENT_SNAPSHOT_CLEANUP_DAYS", "7"))
            self.vacuum_interval_days = int(os.getenv("LONG_AGENT_VACUUM_INTERVAL_DAYS", "30"))

        @property
        def openai_api_key(self) -> str:
            return self._openai_api_key


def init_logging(
    log_level: str = "INFO",
    log_file: str = "logs/agent.log",
    json_format: bool = False,
):
    """初始化日志（带轮转，修复 #7）

    Args:
        log_level: 日志级别
        log_file: 日志文件路径
        json_format: 是否输出 JSON 格式（V2，便于 Grafana Loki 采集）
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    from logging.handlers import RotatingFileHandler

    root = logging.getLogger("long_agent")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if json_format:
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件输出（轮转：10MB × 5个备份）
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return root


class _JsonFormatter(logging.Formatter):
    """JSON 格式日志 — V2

    输出格式：
    {"timestamp": "...", "level": "...", "logger": "...", "message": "..."}

    符合 G-005 日志规范，不含敏感数据。
    便于 Grafana Loki / ELK 采集和查询。
    """

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False)
