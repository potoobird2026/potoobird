# 执行层 — 模块标准

> **版本**：v2.1 | **日期**：2026-05-03
> **设计文档**：03_执行层设计.md

---

## 一、模块定位

执行层是 Agent 的"双手"，负责将计划转化为具体执行步骤，监控执行过程，检测偏离并纠偏。

**核心约束（主心骨）**：
> **BSupervisor 基于 PID 控制器原理监控执行。GoalAnchor 用多维度偏离度向量 + 动态阈值 + 四级纠偏。所有参数不写死，由公式/LLM/用户互动三个维度获得。目标是可验证的，执行结束必须有交付物。**

---

## 二、接口规范

> 详见 `CONTRACT.md`

---

## 三、模块规则

### EX-001：BSupervisor — 执行监督器

**PID 控制器原理**：
- P（比例）：当前偏差 → 立即纠偏
- I（积分）：累积偏差 → 消除稳态误差
- D（微分）：偏差变化率 → 预测未来趋势

**执行流程**：
1. 接收 `(intent, plan)` 参数
2. 分解为 TaskStep 列表
3. 逐步执行，每步创建快照
4. 调用 GoalAnchor 检查偏离
5. 偏离超阈值 → 纠偏（continue/correct/ask_user/stop）

**降级逻辑**：
- BSupervisor 不可用时，AgentLoop 直接执行（V1 兼容）

### EX-002：GoalAnchor — 目标锚定器

**多维度偏离度向量**：
- 方向偏离：余弦相似度（TF-IDF 向量空间模型）
- 结构偏离：Levenshtein 编辑距离（Levenshtein, 1966）
- 意图偏离：Jaccard 相似度（Jaccard, 1901）

**动态阈值**：
- 公式：`threshold = base + 0.4 × progress²`
- progress=0 → 宽松（允许探索）
- progress=1 → 严格（确保交付物一致）
- base 值由 LLM 根据任务类型动态评估

**四级纠偏动作**：
| 动作 | 条件 |
|------|------|
| continue | 偏离在阈值内 |
| correct | 轻微偏离，自动纠偏 |
| ask_user | 中度偏离，询问用户 |
| stop | 严重偏离，停止执行 |

### EX-003：SnapshotManager — 快照管理
- 每步执行前创建快照
- 支持回滚到任意快照
- 快照包含完整执行状态

### EX-004：ToolRegistry — 工具注册
- 工具的注册发现机制
- 工具调用的安全封装
- 工具执行结果记录

### EX-005：参数不写死
- PID 参数（kp/ki/kd）：由 Ziegler-Nichols 方法在线整定
- 基础阈值：由 LLM 根据任务类型动态评估
- 纠偏动作阈值：由 LLM 根据任务风险等级动态调整

---

## 四、依赖

- **全局标准**：`GLOBAL_STANDARDS.md`
- **依赖模块**：`config`（读取执行参数）
- **被依赖模块**：`loop`（AgentLoop._step_execute 调用 BSupervisor）

---

## 五、变更记录

| 日期 | 变更内容 |
|------|----------|
| 2026-05-03 | 初版创建（空目录） |
| 2026-05-03 | 补全：基于 b_supervisor.py + goal_anchor.py + snapshot_manager.py + tool_registry.py 实际代码 + 03_执行层设计，添加 EX-001~EX-005 规则，PID 控制器，四级纠偏，动态阈值 |
