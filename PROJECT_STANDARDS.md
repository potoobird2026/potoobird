# PROJECT_STANDARDS.md — Long Agent 项目标准配置

> **版本**：v2.1 | **日期**：2026-05-03
> **定位**：本项目从全局标准中选取哪些标准、做哪些定制。

---

## 一、项目信息

| 项目 | Long Agent |
|------|-----------|
| 版本 | v2.1 |
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI |
| 数据库 | SQLite（MVP）→ PostgreSQL（V3） |
| LLM | OpenAI API（主）+ 本地 Ollama（降级） |
| 包管理 | pip + requirements.txt |
| 测试框架 | pytest + pytest-asyncio |

---

## 二、启用的全局标准

| 标准 | 状态 | 说明 |
|------|------|------|
| G-001 配置外部化 | ✅ 启用 | Pydantic Settings + .env |
| G-002 统一错误处理 | ✅ 启用 | `src/errors/types.py` 错误体系 |
| G-003 命名一致性 | ✅ 启用 | Python snake_case / PascalCase |
| G-004 防御性编程 | ✅ 启用 | 入口验参 + 外部调用保护 |
| G-005 日志规范 | ✅ 启用 | logging 模块，4 级别 |
| G-006 架构先行 | ✅ 启用 | DESIGN-V2.md 已输出 |
| G-007 决策追溯 | ✅ 启用 | ADR/ 目录，6 篇 ADR |
| G-008 安全基线 | ✅ 启用 | 输入验证 + 参数化查询 + 输出编码 |
| G-009 可交接性 | ✅ 启用 | 12个模块 STANDARD.md + CONTRACT.md |
| G-010 密钥管理 | ✅ 启用 | Secret 不打印、不编造 |
| G-011 变更影响评估 | ✅ 启用 | 修改前 grep 引用 + 修改顺序 |

---

## 三、模块清单

| 模块 | 目录 | STANDARD | CONTRACT | 状态 |
|------|------|----------|----------|------|
| config | `src/config/` | ✅ | ✅ | ✅ 完成 |
| memory | `src/memory/` | ✅ | ✅ | ✅ 完成 |
| understanding | `src/understanding/` | ✅ | ✅ | ✅ 完成 |
| security | `src/security/` | ✅ | ✅ | ✅ 完成 |
| llm | `src/llm/` | ✅ | ✅ | ✅ 完成 |
| algorithms | `src/context/algorithms/` | ✅ | ✅ | ✅ 完成 |
| loop | `src/loop/` | ✅ | ✅ | ✅ 完成 |
| context | `src/context/` | ✅ | ✅ | ✅ 完成 |
| execution | `src/execution/` | ✅ | ✅ | ✅ 完成 |
| delivery | `src/delivery/` | ✅ | ✅ | ✅ 完成 |
| session | `src/session/` | ✅ | ✅ | ✅ 完成 |
| personality | `src/personality/` | ✅ | ✅ | ✅ 完成 |

---

## 四、测试配置

- **框架**：pytest + pytest-asyncio
- **覆盖率**：pytest-cov
- **门禁**：行 ≥ 80%（核心 ≥ 90%），分支 ≥ 75%，函数 ≥ 90%
- **当前**：629 passed

---

## 五、项目目录结构

```
long2/
├── AGENTS.md
├── GLOBAL_STANDARDS.md
├── PROJECT_STANDARDS.md
├── REQUIREMENTS.md
├── DESIGN-V2.md
├── TASKS.md
├── COMMUNICATION_LOG.md
├── CHARTER.md
├── ADR/
│   ├── 001-技术选型.md
│   ├── 002-架构模式.md
│   ├── 003-步骤方法状态转换移除.md
│   ├── 004-构建计划函数改为模块级.md
│   ├── 005-记忆系统三层架构.md
│   ├── 006-上下文压缩三阶段算法.md
│   └── 007-v2-module-injection.md
├── modules/
│   ├── algorithms/
│   ├── config/
│   ├── context/
│   ├── delivery/
│   ├── execution/
│   ├── llm/
│   ├── loop/
│   ├── memory/
│   ├── personality/
│   ├── security/
│   ├── session/
│   └── understanding/
├── src/
│   ├── audit/
│   ├── background/
│   ├── config/
│   ├── context/
│   │   ├── algorithms/
│   │   └── compressor.py
│   ├── delivery/
│   ├── entry/
│   ├── errors/
│   ├── execution/
│   ├── llm/
│   ├── loop/
│   ├── memory/
│   ├── observability/
│   ├── personality/
│   ├── security/
│   ├── session/
│   ├── tools/
│   └── understanding/
└── tests/
    └── unit/
```

---

> **维护者**：BOSS 审批，Agent 执行
> **变更记录**：
> - 2026-05-03：初版创建
