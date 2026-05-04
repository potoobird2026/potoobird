# 配置管理 — 模块标准

> **版本**：v2.1 | **日期**：2026-05-03
> **设计文档**：01_记忆系统全局设计.md §二、三层记忆架构

---

## 一、模块定位

配置管理模块是整个系统的基础设施层，所有其他模块通过它获取运行时参数。

**核心约束（主心骨）**：
> **所有配置通过 Pydantic Settings 管理，禁止硬代码。加载优先级：环境变量 > .env > 默认值。API Key 使用 Fernet 加密存储，永不以明文写入代码或日志。**

---

## 二、接口规范

> 详见 `CONTRACT.md`

---

## 三、模块规则

### C-001：配置外部化（对应 G-001）
- 所有 URL、密码、路径、端口、超时、重试次数必须通过 `Settings` 类读取
- 禁止在代码中硬编码任何连接字符串或密钥
- 环境变量前缀统一为 `LONG_AGENT_`

### C-002：API Key 安全存储
- API Key 支持两种模式：
  - **开发模式**：环境变量 `LONG_AGENT_OPENAI_API_KEY` 明文读取
  - **生产模式**：环境变量 `LONG_AGENT_OPENAI_API_KEY_ENCRYPTED` 存储 Fernet 加密值
- 运行时通过 `settings.openai_api_key` 属性自动解密
- 解密失败时返回空字符串并记录错误日志，**不抛出异常**

### C-003：Fernet 密钥管理
- 密钥文件路径：`data/.fernet_key`
- 文件不存在时自动生成新密钥
- Linux/Mac：文件权限 `0o600`（仅当前用户可读写）
- Windows：通过 `icacls` 移除继承权限，仅当前用户完全控制

### C-004：降级兼容
- 当 `pydantic_settings` 不可用时，自动降级为纯 `os.getenv()` 读取
- 降级时所有配置项仍有默认值，系统不崩溃

### C-005：日志初始化
- 日志格式统一：`%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- 文件输出使用 `RotatingFileHandler`：单文件 10MB，保留 5 个备份
- 日志级别只允许 `DEBUG / INFO / WARNING / ERROR`，其他值抛 `ValueError`

### C-006：配置项清单（当前版本）

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| llm_provider | LONG_AGENT_LLM_PROVIDER | openai | LLM 提供商 |
| openai_api_key_encrypted | LONG_AGENT_OPENAI_API_KEY_ENCRYPTED | "" | 加密存储的 API Key |
| openai_model | LONG_AGENT_OPENAI_MODEL | gpt-4o | 模型名称 |
| llm_timeout | LONG_AGENT_LLM_TIMEOUT | 30 | LLM 调用超时(秒)，范围 5~120 |
| llm_max_retries | LONG_AGENT_LLM_MAX_RETRIES | 3 | 最大重试次数，范围 0~10 |
| database_path | LONG_AGENT_DATABASE_PATH | data/memory.db | SQLite 数据库路径 |
| data_dir | LONG_AGENT_DATA_DIR | data | 数据目录 |
| backup_dir | LONG_AGENT_BACKUP_DIR | data/backups | 备份目录 |
| backup_keep | LONG_AGENT_BACKUP_KEEP | 3 | 保留备份数，范围 1~10 |
| log_level | LONG_AGENT_LOG_LEVEL | INFO | 日志级别 |
| log_file | LONG_AGENT_LOG_FILE | logs/agent.log | 日志文件路径 |
| backup_interval_hours | LONG_AGENT_BACKUP_INTERVAL_HOURS | 24 | 备份间隔(小时)，范围 1~168 |
| snapshot_cleanup_days | LONG_AGENT_SNAPSHOT_CLEANUP_DAYS | 7 | 快照清理天数，≥1 |
| vacuum_interval_days | LONG_AGENT_VACUUM_INTERVAL_DAYS | 30 | 数据库 vacuum 间隔(天)，≥1 |

---

## 四、依赖

- **全局标准**：`GLOBAL_STANDARDS.md`
- **依赖模块**：无（配置层是最底层，不依赖其他业务模块）
- **被依赖模块**：memory / llm / security / session / loop（所有模块）

---

## 五、变更记录

| 日期 | 变更内容 |
|------|----------|
| 2026-05-03 | 初版创建（空壳） |
| 2026-05-03 | 补全：基于 settings.py 实际代码 + 01_全局设计，添加 C-001~C-006 规则，Fernet 加密流程，配置项完整清单 |
