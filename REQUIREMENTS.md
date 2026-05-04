# REQUIREMENTS.md — Long Agent 需求文档

> **版本**：v2.1 | **日期**：2026-05-03 | **状态**：开发中

---

## 一、业务目标（一句话）

开发一个以交付为核心的 AI Agent 系统，以三层记忆为资产，能理解用户意图、执行可验证的任务、并持续自我优化。

---

## 二、功能需求

### V1 已完成

| # | 需求 | 状态 |
|---|------|------|
| F-001 | 三层记忆系统（人格 HEXACO + 核心 SQLite + 标准 Markdown） | ✅ |
| F-002 | 意图解析 + 追问策略 | ✅ |
| F-003 | 冲突检测 + 输入过滤 + 危险操作暂停 | ✅ |
| F-004 | CLI 交互 | ✅ |
| F-005 | LLM 调用层（OpenAI） | ✅ |
| F-006 | 配置系统（Pydantic Settings） | ✅ |
| F-007 | 日志 + 指标采集 | ✅ |

### V2 规划

| # | 需求 | 状态 |
|---|------|------|
|| F-008 | 上下文压缩引擎升级（三阶段） | ✅ |
| F-009 | 执行层（BSupervisor + GoalAnchor + ToolRegistry） | ✅ |
| F-010 | 交付层（ResultVerifier + ReportGenerator + ConfirmationManager） | ✅ |
| F-011 | LLM 管理（ModelRouter + PromptManager） | ✅ |
| F-012 | 会话管理（SessionManager + EventBus） | ✅ |
| F-013 | 状态机完善 | ✅ |
| F-014 | 安全审批模块（SecurityGuard + ApprovalModule） | ✅ |
| F-015 | 人格系统完善（7 种算法） | ✅ |
| F-016 | 可观测性升级（Prometheus + Grafana） | ✅ |
| F-017 | 记忆系统联动（MemoryLoader + MemoryEvictor + 宽进严出） | ✅ |
| F-018 | AgentLoop 主循环打通（V2 组件注入） | ✅ |

---

## 三、非功能需求

| # | 需求 | 指标 |
|---|------|------|
| NF-001 | 核心模块测试覆盖率 | ≥ 95% |
| NF-002 | 非核心模块测试覆盖率 | ≥ 80% |
| NF-003 | 整体测试覆盖率 | ≥ 85% |
| NF-004 | 关键操作响应时间 | < 500ms |
| NF-005 | LLM 调用失败重试 | 3 次 |
| NF-006 | 危险操作可中断 | 支持 |

---

## 四、约束条件

1. Python 3.12+ / FastAPI / SQLite / OpenAI API
2. 单用户 Agent
3. CLI 先行，V2 再加 Web
4. 配置外部化（禁止硬编码）
5. 所有模块必须有 STANDARD.md + CONTRACT.md

---

## 五、不做什么

| 不做 | 原因 |
|------|------|
| 多模型路由 | V2 再考虑 |
| Web UI | CLI 先行 |
| 多用户 | 单用户 Agent |
| 插件系统 | 复杂度太高 |
| ACP 协议 | 内部使用 |

---

## 六、需求渐进对齐记录

| 日期 | 变更 | 影响评估 | 操作人 |
|------|------|---------|--------|
| 2026-05-03 | 初版需求创建 | — | Agent |
| 2026-05-03 | 标准体系从 PS/CS/AS/QS 改为两层架构（全局+模块） | 全局性变更，所有文档引用需同步 | Agent + BOSS |
| 2026-05-03 | 确认开发流程：架构先行→模块化→主心骨→持续对齐→需求渐进融入 | 核心流程变更，需写入 AGENTS.md | BOSS |
| 2026-05-03 | 记忆系统5个设计决策写入代码和文档（ADR-008/009/010、G-012、memory_loader.py、memory_evictor.py） | 记忆系统核心架构变更 | Agent + BOSS |
| 2026-05-04 | V2-T13 AgentLoop主循环打通（_load_memory_context接V2动态加载，_step_reflect接淘汰检查） | 主循环核心逻辑变更 | Agent |
| 2026-05-04 | V2-T14 全局对齐检查+文档补全（TASKS/REQUIREMENTS/DESIGN版本号统一、ADR编号修正、功能清单状态同步） | 文档全局对齐 | Agent |

---

> **下一步**：V2-T15 补齐缺失模块的单元测试（GoalAnchor、SnapshotManager、ToolRegistry、ModelRouter、SessionManager、EventBus、SecurityGuard）
