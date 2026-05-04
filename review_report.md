# 代码审查报告 — 问题清单

> 审查方式：按 standard_alignment SKILL 逐模块审查
> 审查时间：2026-05-04

---

## 🔴 P0：功能缺失（影响正常运行）

### 问题1：CLI 入口未注入 V2 模块
**文件**：`src/entry/cli.py` → `create_agent()`
**现状**：只注入了 memory + understanding + security + llm_provider
**缺少的模块**：compressor, b_supervisor, goal_anchor, snapshot_manager, result_verifier, report_generator, session_manager, background_compressor, personality_fusion, approval_module, conflict_checker, credential_pool
**影响**：AgentLoop 的 29 个构造函数参数大部分为 None，V2 功能全部降级为 V1
**需要**：在 `create_agent()` 中创建并注入所有 V2 模块

### 问题2：InputFilter 安全过滤被注释掉
**文件**：`src/loop/agent_loop.py:336`
**代码**：`# V2: filter_result = self.security.filter(ctx.user_input)`
**影响**：用户输入没有经过安全检查直接进入主循环
**需要**：取消注释并在 `__init__` 中注入 security 参数

---

## 🟡 P1：算法不完整

### 问题3：人格算法只有 3 种（设计要 7 种）
**文件**：`src/personality/algorithms.py`
**设计**：PID + 卡尔曼 + 贝叶斯 + 模糊 + 熵 + UCB1 + RL（7种）
**代码**：仅有 PID + 卡尔曼 + 模糊（3种）
**缺少**：贝叶斯推断、信息熵控制器、多臂老虎机、Q-Learning
**影响**：人格调整策略单一，无法从噪声反馈中提取真实偏好

### 问题4：compressor 的 10 算法评分缺关键算法
**文件**：`src/context/compressor.py`
**设计**：10 算法融合（遗忘曲线+信息熵+序参量+CUSUM+PageRank+矛盾检测+混沌边缘+情感权重+实体保留+LLM评分）
**代码**：注释写了 10 算法，但实际 `score_memory()` 只有遗忘曲线和 CUSUM
**需要**：补充缺失的 8 个评分函数

---

## 🟠 P2：主循环未接入

### 问题5：ApprovalModule 未接入 `_step_plan`
**现状**：`_step_plan` 仅设置了 requires_approval 标记
**缺少**：调用 `approval_module.evaluate_risk()` 做动态风险评估
**影响**：所有操作都不经过风险审批

### 问题6：GoalAnchor 未接入 `_step_observe`
**现状**：`_step_observe` 没有调用 `goal_anchor.check()`
**缺少**：目标偏离度检测 + PID 纠偏
**影响**：Agent 执行过程中跑偏了不会被发现

### 问题7：人格融合引擎虽已注入但未产生实际效果
**现状**：`_step_perceive` 调用了 `PersonalityFusionEngine` 计算调节量
**缺少**：计算结果没有被应用到 MemoryManager 的人格数据上
**影响**：人格调节"算了白算"，用户反馈不改变行为

### 问题8：记忆淘汰引擎未接入
**现状**：`_step_reflect` 的淘汰检查被注释
**影响**：记忆只增不减，最终会撑爆数据库

---

## 🔵 P3：接口不匹配

### 问题9：web_ui.py 未集成到项目入口
**现状**：`web_ui.py` 独立运行（`uvicorn`），未在 `cli.py` 中注册
**影响**：用户需要单独启动 Web 服务，不能 `python -m src.entry run --web`

### 问题10：SessionManager 接口与主循环不匹配
**现状**：SessionManager 的 `on_message(channel, channel_user_id, ...)` 需要渠道和用户 ID 参数
**主循环需要**：简单的 `on_message(user_input)` 接口
**影响**：主循环无法直接调用 SessionManager

---

## 📊 总结

| 级别 | 问题数 | 说明 |
|------|--------|------|
| 🔴 P0 | 2 | 功能缺失，影响正常运行 |
| 🟡 P1 | 2 | 算法不完整 |
| 🟠 P2 | 3 | 主循环未接入关键模块 |
| 🔵 P3 | 2 | 接口不匹配 |
| **合计** | **9** | |

**核心结论**：
1. 主循环的 **7 步框架是完整的**
2. 各模块代码**编写了但入口没注入**（最重要的根因）
3. 算法**设计丰富但实现不全**
4. 人格系统**3/7 算法实现，且未产生实际效果**
