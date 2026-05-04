# 配置管理 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## Settings 类

### 实例化

```python
from src.config.settings import Settings

settings = Settings()  # 自动读取 .env 和环境变量
```

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `llm_provider` | `str` | LLM 提供商名称 |
| `openai_api_key` | `str` | **property**，自动解密的 API Key |
| `openai_model` | `str` | 模型名称 |
| `llm_timeout` | `int` | 超时秒数 (5~120) |
| `llm_max_retries` | `int` | 最大重试次数 (0~10) |
| `database_path` | `str` | 数据库文件路径 |
| `data_dir` | `str` | 数据目录 |
| `backup_dir` | `str` | 备份目录 |
| `backup_keep` | `int` | 保留备份数 (1~10) |
| `log_level` | `str` | DEBUG/INFO/WARNING/ERROR |
| `log_file` | `str` | 日志文件路径 |
| `backup_interval_hours` | `int` | 备份间隔小时 (1~168) |
| `snapshot_cleanup_days` | `int` | 快照清理天数 (≥1) |
| `vacuum_interval_days` | `int` | vacuum 间隔天数 (≥1) |

### 加密函数

```python
from src.config.settings import _encrypt, _decrypt

encrypted: str = _encrypt("sk-xxx...")  # 加密
plain: str = _decrypt(encrypted)         # 解密
```

### 日志初始化

```python
from src.config.settings import init_logging

init_logging(log_level="INFO", log_file="logs/agent.log")
```

---

## 降级模式

当 `pydantic_settings` 不可用时，`Settings` 类自动退化为纯 `os.getenv()` 实现。接口不变，调用方无需感知。

---

## 环境变量完整清单

| 环境变量 | 对应属性 | 示例值 |
|----------|----------|--------|
| `LONG_AGENT_LLM_PROVIDER` | `llm_provider` | `openai` |
| `LONG_AGENT_OPENAI_API_KEY` | `openai_api_key`（明文） | `sk-xxx` |
| `LONG_AGENT_OPENAI_API_KEY_ENCRYPTED` | `openai_api_key`（加密） | `gAAAAAB...` |
| `LONG_AGENT_OPENAI_MODEL` | `openai_model` | `gpt-4o` |
| `LONG_AGENT_LLM_TIMEOUT` | `llm_timeout` | `30` |
| `LONG_AGENT_LLM_MAX_RETRIES` | `llm_max_retries` | `3` |
| `LONG_AGENT_DATABASE_PATH` | `database_path` | `data/memory.db` |
| `LONG_AGENT_DATA_DIR` | `data_dir` | `data` |
| `LONG_AGENT_BACKUP_DIR` | `backup_dir` | `data/backups` |
| `LONG_AGENT_BACKUP_KEEP` | `backup_keep` | `3` |
| `LONG_AGENT_LOG_LEVEL` | `log_level` | `INFO` |
| `LONG_AGENT_LOG_FILE` | `log_file` | `logs/agent.log` |
| `LONG_AGENT_BACKUP_INTERVAL_HOURS` | `backup_interval_hours` | `24` |
| `LONG_AGENT_SNAPSHOT_CLEANUP_DAYS` | `snapshot_cleanup_days` | `7` |
| `LONG_AGENT_VACUUM_INTERVAL_DAYS` | `vacuum_interval_days` | `30` |
