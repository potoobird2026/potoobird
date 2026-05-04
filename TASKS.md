# TASKS.md — Long Agent 任务列表

> **更新规则**：每完成一个任务立即更新状态。

---

## V1 已完成

| ID | 任务 | 状态 |
|----|------|------|
| V1-T01 | 项目初始化（CHARTER + 目录结构） | ✅ |
| V1-T02 | 记忆系统（三层 + 存储 + 审计） | ✅ |
| V1-T03 | 理解层（意图 + 追问 + 规则兜底） | ✅ |
| V1-T04 | 安全模块（5 层过滤 + LLM 语义检测） | ✅ |
| V1-T05 | LLM 调用层（抽象接口 + OpenAI） | ✅ |
| V1-T06 | Agent 主循环（7 步 + 状态机） | ✅ |
| V1-T07 | 配置系统（Pydantic Settings） | ✅ |
| V1-T08 | 可观测性（日志 + 指标） | ✅ |
| V1-T09 | 后台任务（事件驱动） | ✅ |

## V2 开发中

### 阶段一：打通主干

| ID | 任务 | 状态 |
|----|------|------|
| V2-T01 | BSupervisor 接入主循环 | ✅ |
| V2-T02 | 交付层（ResultVerifier + ReportGenerator）接入 | ✅ |
| V2-T03 | ContextCompressor 注入主循环 | ✅ |
| V2-T04 | MemoryManager V2 接口补齐 | ✅ |
| V2-T05 | 状态机完善（触发器 + 进入/退出动作） | ✅ |

### 阶段二：新增模块

| ID | 任务 | 状态 |
|----|------|------|
| V2-T06 | LLM 管理模块（ModelRouter + PromptManager） | ✅ |
| V2-T07 | 会话管理模块（SessionManager + EventBus） | ✅ |
| V2-T08 | 安全审批模块（SecurityGuard） | ✅ |

### 阶段三：完善与交付

| ID | 任务 | 状态 |
|----|------|------|
| V2-T09 | 人格系统完善（7 种算法） | ✅ |
| V2-T10 | 可观测性升级（Prometheus + Grafana） | ✅ |
| V2-T11 | 清理硬编码值（context_window + K值 + identity_manager） | ✅ |
| V2-T12 | 记忆系统5个设计决策写入代码和文档 | ✅ |
| V2-T13 | AgentLoop 主循环打通（V2 组件注入） | ✅ |
| V2-T14 | 全局对齐检查 + 文档补全 | ✅ |
| V2-T15 | 补齐缺失模块的单元测试（7个模块） | ✅ |
| V2-T16 | 集成测试 + 端到端验证 | ⬜ |

### 阶段四：代码补齐（V2 审计修复）

> 2026-05-04：全量扫描发现9个类+29个函数未实现，全部补齐。

| ID | 任务 | 状态 | 新增文件 |
|----|------|------|----------|
| V2-A01 | SubAgentManager + SubAgentStatus | ✅ | `src/execution/sub_agent_manager.py` |
| V2-A02 | ProcessStandard | ✅ | `src/execution/process_standard.py` |
| V2-A03 | IdentityManager | ✅ | `src/session/identity_manager.py` |
| V2-A04 | SessionManager 重构 | ✅ | `src/session/session_manager.py` |
| V2-A05 | AgentStateMachine + TransitionTrigger + StatePersistence | ✅ | `src/loop/state.py`（追加） |
| V2-A06 | CredentialPoolV2（AES-256-GCM + PBKDF2） | ✅ | `src/security/guard.py`（追加） |
| V2-A07 | _llm_analyze_conflict | ✅ | `src/security/guard.py`（追加） |
| V2-A08 | PromptManagerV2（render_prompt + record_feedback + Thompson Sampling） | ✅ | `src/llm/prompt_manager.py`（追加） |
| V2-A09 | PrometheusExporter + save_state/load_state | ✅ | `src/observability/prometheus_exporter.py` |

---

### 阶段五：V1 遗留清理

| ID | 任务 | 状态 |
|----|------|------|
| V2-C01 | 删除 V1 遗留文件 confidence_threshold.py（175行，零 import） | ✅ |
| V2-C02 | 删除 V1 遗留文件 logistic_growth.py（373行，零 import） | ✅ |

---

> **当前阶段**：阶段三（完善与交付）
> **当前任务**：V2-A01~A09 全部补齐完成，V2-C01~C02 清理完成，V2-T16 集成测试待执行
