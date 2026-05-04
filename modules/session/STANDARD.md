# 会话管理 — 模块标准

> **版本**：v2.1 | **日期**：2026-05-03
> **设计文档**：08_会话管理设计.md

---

## 一、模块定位

会话管理模块是 Agent 的"会客厅"，负责会话的完整生命周期（创建/加载/保存/销毁），管理会话上下文、用户身份和事件通信。

**核心约束（主心骨）**：
> **会话状态机驱动（active→idle→expired→closed），超时从用户行为自适应学习。身份与会话解耦，一个用户可有多个会话。EventBus 解耦模块间通信，事件不丢失。**

---

## 二、接口规范

> 详见 `CONTRACT.md`

---

## 三、模块规则

### SS-001：SessionManager — 会话生命周期

**会话状态**：
| 状态 | 说明 | 转换条件 |
|------|------|----------|
| active | 活跃中 | 有交互时 |
| idle | 空闲 | 无交互超 idle_timeout |
| expired | 过期 | 空闲超 expire_timeout |
| closed | 关闭 | 用户主动关闭或 Agent 关闭 |

**自适应超时**：
- 初始 idle_timeout：3600 秒（1 小时）
- 运行后从用户历史行为自适应学习
- 不写死

**上下文窗口**：
- 基于 token 计数动态调整
- 超出窗口时调用 ContextCompressor

### SS-002：IdentityManager — 身份管理

**身份与会话解耦**：
- 一个用户可有多个会话
- 用户身份独立于会话存在
- 支持用户切换

**职责**：
- 用户身份验证
- 用户配置管理
- 多用户支持（V2 扩展）

### SS-003：EventBus — 事件总线

**模块间解耦通信**：
- 发布/订阅模式
- 事件不丢失（持久化到内存队列）
- 支持异步事件处理

**事件类型**：
- `session.created` / `session.expired` / `session.closed`
- `message.received` / `message.sent`
- `intent.parsed` / `intent.confirmed`
- `execution.started` / `execution.completed` / `execution.failed`
- `verification.passed` / `verification.failed`

### SS-004：会话数据隔离
- 每个会话的上下文数据完全隔离
- 会话间不共享内存
- 会话销毁后数据可持久化到 SQLite

### SS-005：V2 扩展方向
- 多会话并发管理
- 会话持久化（SQLite/Redis）
- 会话恢复（崩溃恢复）

---

## 四、依赖

- **全局标准**：`GLOBAL_STANDARDS.md`
- **依赖模块**：
  - `config`（读取超时参数、数据目录）
  - `context`（上下文压缩）
- **被依赖模块**：`loop`（AgentLoop 通过 SessionManager 管理会话）

---

## 五、变更记录

| 日期 | 变更内容 |
|------|----------|
| 2026-05-03 | 初版创建（空目录） |
| 2026-05-03 | 补全：基于 session_manager.py + identity_manager.py + event_bus.py 实际代码 + 08_会话管理设计，添加 SS-001~SS-005 规则，会话状态机，自适应超时，EventBus 事件清单 |
