# 上下文压缩 — 模块标准

> **版本**：v2.2 | **日期**：2026-05-04
> **代码**：`src/context/compressor.py`

---

## 一、模块定位

上下文压缩模块是 Agent 的"记忆消化系统"，负责在对话历史超出 LLM 上下文窗口时，智能裁剪和压缩历史消息。

**核心约束（主心骨）**：
> **双锚点保边 + 10算法融合评分 + 幂律裁剪。所有参数不写死，由公式/LLM/用户互动三个维度获得。压缩质量必须自评。**

---

## 二、接口规范

> 详见 `CONTRACT.md`

---

## 三、模块规则

### CT-001：压缩流程（V2）

```
双锚点保边 → 10算法融合评分 → 幂律裁剪
```

**阶段1：双锚点保边**（`_get_dual_anchor_bounds`）
- 保留最早 M 条锚点（实体定义/关键决策，由 `DualAnchorStrategy.count_anchors` 计算）
- 保留最近 N 条工作记忆（信息熵驱动，由 `DualAnchorStrategy.calc_recent_window` 计算）
- 只压缩中间区域

**阶段2：10算法融合评分**（`score_memory`）
- 对中间区域每条消息打价值分
- 权重 `w_i = conf_i / Σconf_j`（置信度归一化），低置信度算法自动降权

| # | 算法 | 评分维度 | 科学依据 |
|---|------|----------|----------|
| 1 | `_score_forgetting` | 时效性 | Ebbinghaus 遗忘曲线, 1885 |
| 2 | `_score_access_frequency` | 访问频率 | 记忆强度理论 |
| 3 | `_score_recency` | 最近度 | 近因效应 |
| 4 | `_score_relevance` | 相关性 | 余弦相似度近似 |
| 5 | `_score_layer_weight` | 层权重 | 三层记忆架构（人格/核心/标准） |
| 6 | `_score_contradiction` | 矛盾检测 | 一致性检验 |
| 7 | `_score_topic_consistency` | 话题一致性 | 话题切换检测 |
| 8 | `_score_anchor` | 锚点分数 | 实体定义/关键决策 |
| 9 | `_score_value_density` | 价值密度 | 信息密度评估 |
| 10 | `_score_power_law` | 幂律分数 | Clauset et al., 2009 |

**阶段3：幂律裁剪**（`apply_power_law_pruning`）
- 按评分排序，幂律分布裁剪低价值消息
- 裁剪指数 α 初始值由 `_calc_initial_alpha` 计算（信息熵驱动）
- 运行时根据质量反馈调整：`α_{t+1} = α_t × (1 + λ × quality_feedback)`

### CT-002：双锚点策略（DualAnchorStrategy）

- `is_anchor(msg)`：判断消息是否为不可压缩锚点（第一条用户消息 OR 含实体关键词 OR 来自 user/assistant 角色）
- `count_anchors(messages)`：计算锚点消息数 M
- `calc_recent_window(messages)`：计算最近保留窗口 N（信息熵驱动）

### CT-003：后台压缩进程（BackgroundCompressor）

- 状态机：SLEEP → COMPRESSING → MONITORING → SLEEP
- `signal_maybe_compress(session)`：非阻塞检查，超过阈值触发后台压缩
- 分批压缩，零阻塞对话路径

### CT-004：反馈引擎（FeedbackEngine）

- 5类信号：`compression_loss`（信息损失）、`topic_drift`（话题漂移）、`entity_loss`（实体丢失）、`contradiction_introduced`（引入矛盾）、`user_correction`（用户纠正）
- 驱动 α 自适应调整

### CT-005：参数自适应

| 参数 | 来源 | 公式/方法 |
|------|------|-----------|
| 锚点数量 M | 公式 | `DualAnchorStrategy.count_anchors()` |
| 最近窗口 N | 公式 | `DualAnchorStrategy.calc_recent_window()` |
| 初始 α | 公式 | `_calc_initial_alpha()`（信息熵幂律拟合） |
| 算法权重 w_i | 公式 | `conf_i / Σconf_j` |
| 运行时 α | LLM反馈 | `α_t × (1 + λ × quality_feedback)` |

---

## 四、依赖

- **全局标准**：`GLOBAL_STANDARDS.md`
- **依赖模块**：`config`（读取压缩参数配置）
- **被依赖模块**：`loop`（AgentLoop._step_perceive 调用压缩）、`session`（SessionManager 上下文压缩）

---

## 五、变更记录

| 日期 | 变更内容 |
|------|----------|
| 2026-05-03 | 初版创建 |
| 2026-05-03 | 补全：基于 compressor.py 实际代码 + 09_压缩引擎v1.3 |
| 2026-05-04 | **v2.2 对齐实际代码**：删除 V1/V2 兼容描述（已无 V1）；更新10算法清单为实际实现的10个 `_score_*` 方法；删除 CUSUM/余弦相似度/Jaccard/TF-IDF/LLM评分（未实现）；删除 CT-003 V1/V2 兼容（已统一为 CompressResult 9字段）；更新科学依据表格 |
