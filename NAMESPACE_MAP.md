# Long Agent — 全局命名空间地图

> **维护者**：BOSS 审批，Agent 执行
> **加载规则**：Agent 在命名任何新模块/类/函数前必须先查阅本文件

---

## 一、模块命名

| 模块 | 目录 | 一句话职责 |
|------|------|-----------|
| Agent 主循环 | `src/loop/` | 7步循环调度 + 状态机 |
| 记忆系统 | `src/memory/` | 三层记忆读写 + 淘汰 |
| 理解层 | `src/understanding/` | 意图解析 + 追问策略 |
| 上下文压缩 | `src/context/` | 多算法融合压缩 |
| 人格算法 | `src/personality/` | HEXACO 7种调整算法 |
| 执行层 | `src/execution/` | 任务监督 + 工具调用 |
| 交付层 | `src/delivery/` | 结果验证 + 报告生成 |
| LLM 管理 | `src/llm/` | 模型路由 + Prompt管理 |
| 安全模块 | `src/security/` | 输入过滤 + 审批 |
| 会话管理 | `src/session/` | 跨渠道会话 |
| 可观测性 | `src/observability/` | 指标采集 + 健康检查 |
| 后台任务 | `src/background/` | 事件驱动维护 |
| 入口 | `src/entry/` | CLI + Web UI |
| 配置 | `src/config/` | 环境变量 + 设置 |
| 错误处理 | `src/errors/` | 统一错误类型 |
| 工具 | `src/tools/` | 内置工具集 |

## 二、类命名规范

| 类型 | 命名规则 | 示例 |
|------|---------|------|
| 管理器 | `XxxManager` | `MemoryManager`, `SessionManager` |
| 引擎 | `XxxEngine` | `UnderstandingEngine` |
| 器 | `XxxEr` / `XxxOr` | `Compressor`, `Verifier`, `Classifier` |
| 注册表 | `XxxRegistry` | `ToolRegistry` |
| 状态 | `XxxState` | `AgentState`, `PersonalityState` |
| 结果 | `XxxResult` | `LLMResult`, `OperationResult`, `CompressResult` |
| 配置 | `XxxSettings` / `XxxConfig` | `Settings`, `ModelConfig` |
| 快照 | `XxxSnapshot` | `TaskSnapshot` |
| 步骤 | `XxxStep` | `TaskStep` |
| 记录 | `XxxRecord` | `ApprovalRecord` |
| 计划 | `XxxPlan` | `DeliverablePlan` |
| 请求 | `XxxRequest` | `ApprovalRequest` |
| ABC | `AbstractXxx` 或 `Xxx(ABC)` | `LLMProvider`, `MemoryStorage` |

## 三、函数命名规范

| 类型 | 前缀 | 示例 |
|------|------|------|
| 查询 | `get_` / `find_` / `search_` | `get_personality`, `find_by_content` |
| 创建 | `create_` / `new_` | `create_session` |
| 更新 | `update_` / `adjust_` | `adjust_personality` |
| 删除 | `delete_` / `remove_` | `delete_memory` |
| 执行 | `execute_` / `run_` | `execute_task`, `run_step` |
| 检查 | `check_` / `verify_` / `is_` | `check_health`, `is_off_track` |
| 加载 | `load_` / `build_` | `load_personality`, `build_context` |
| 保存 | `save_` / `write_` | `save_snapshot`, `write_log` |
| 转换 | `to_` / `from_` / `parse_` | `to_dict`, `from_isoformat` |
| 处理 | `process_` / `handle_` | `process_input`, `handle_error` |

## 四、文件命名规范

| 类型 | 规则 | 示例 |
|------|------|------|
| 模块文件 | snake_case | `agent_loop.py`, `memory_manager.py` |
| 测试文件 | test_*.py | `test_agent_loop.py` |
| 配置文件 | snake_case | `settings.py` |
| 常量文件 | UPPER_SNAKE | `GLOBAL_STANDARDS.md` |

## 五、布尔值命名

| 前缀 | 含义 | 示例 |
|------|------|------|
| `is_` | 状态判断 | `is_running`, `is_off_track` |
| `has_` | 拥有判断 | `has_conflicts`, `has_key_entity` |
| `can_` | 能力判断 | `can_recover`, `can_compress` |
| `should_` | 建议判断 | `should_compress`, `should_retry` |

## 六、常量命名

```python
# 配置常量
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
CONTEXT_WINDOW = 128000

# 阈值常量
CONFIDENCE_HIGH = 0.85
CONFIDENCE_LOW = 0.50
EVICT_ALPHA = 1.5
K_CAPACITY = 10000
```

## 七、日志命名

```python
# 模块 logger
logger = logging.getLogger("long_agent.module_name")

# 事件类型
"state_transition"  # 状态转换
"memory_write"      # 记忆写入
"memory_search"     # 记忆搜索
"compression"       # 上下文压缩
"execution_step"    # 执行步骤
"verification"      # 结果验证
"security_violation" # 安全违规
```
