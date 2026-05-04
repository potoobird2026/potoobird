# Long Agent — V2 技术设计文档

> **版本**：v2.1 | **日期**：2026-05-03 | **状态**：开发中
> **输入**：`DESIGN.md v1.6` + `记忆模块设计/long/*.md`（01~09，2026-05-03 深度融合版）
> **输出**：本文档 — 定义 V2 完整架构与实现路径

---

## 一、V1 → V2 变更总览

### 1.1 V1 已完成（不重复描述）

| 模块 | V1 完成度 | 代码行数 |
|------|----------|---------|
| 入口系统（CLI + 库） | ✅ 完成 | ~185 |
| Agent 主循环（7 步 + 状态机） | ✅ 完成 | ~772 |
| 记忆系统（三层 + 存储抽象 + 审计） | ✅ 完成 | ~1100 |
| 理解层（意图解析 + 追问 + 规则兜底） | ⚠️ 部分 | ~494 |
| 上下文压缩 | 双锚点 + 10算法融合评分 + 幂律裁剪 | ✅ 完成 | ~757 |
| 安全模块（5 层过滤 + LLM 语义检测） | ✅ 完成 | ~216 |
| LLM 调用层（抽象接口 + OpenAI） | ✅ 完成 | ~167 |
| 后台任务（事件驱动） | ✅ 完成 | ~143 |
| 配置系统（Pydantic Settings） | ✅ 完成 | ~185 |
| 可观测性（日志 + 指标采集） | ✅ 完成 | ~158 |
| **V1 合计** | | **~4989** |

### 1.2 V2 新增 / 升级

| 模块 | 类型 | 说明 |
|------|------|------|
|| **上下文压缩引擎** | 升级 | ✅ 双锚点保边 + 10算法融合评分 + 幂律裁剪 + CompressResult 10字段 |
| **执行层** | 新增 | ✅ BSupervisor + GoalAnchor + ToolRegistry + SnapshotManager |
| **交付层** | 新增 | ✅ ResultVerifier（风险自适应阈值）+ ReportGenerator（分层报告）|
| **LLM 管理** | 新增 | ✅ ModelRouter（回退链 + 冷却）+ PromptManager（Thompson Sampling）|
| **会话管理** | 新增 | ✅ SessionManager + EventBus |
| **状态机完善** | 升级 | ✅ 触发器 + 进入/退出动作 |
| **安全审批模块** | 新增 | ✅ SecurityGuard（三级协商 + 自适应超时）|
| **人格系统完善** | 升级 | ✅ 7 种算法全部实现，参数不写死 |
| **可观测性升级** | 升级 | ✅ Prometheus text format |
| **测试完善** | 升级 | ✅ 核心模块覆盖 + 记忆系统V2测试 |

---

## 二、V2 完整架构

### 2.1 架构总图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Long Agent V2 系统架构                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                        入口系统（V1 已有）                        │   │
│  │   CLI 入口 (typer)  │  库入口 (LongAgent.create())               │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                          │
│                              ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      Agent 主循环（V1 已有）                      │   │
│  │  ①感知→②理解→③规划→④执行→⑤观察→⑥反思→⑦回复                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│         │           │           │           │           │               │
│         ▼           ▼           ▼           ▼           ▼               │
│  ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌────────────┐       │
│  │ 记忆系统  ││ 理解层   ││ 安全审批  ││LLM 管理  ││ 会话管理   │       │
│  │ (V2 升级) ││ (V2 升级) ││ (V2 新增) ││ (V2 新增) ││ (V2 新增)  │       │
│  │          ││          ││          ││          ││            │       │
│  │三层记忆   ││意图解析   ││SecurityGuard││ModelRouter││SessionMgr  │       │
│  │7种人格算法││双锚点+10算法││ApprovalModule││PromptMgr ││IdentityMgr │       │
│  │参数不写死 ││参数不写死 ││ConflictChecker││回退链    ││EventBus    │       │
│  │          ││          ││CredentialPool││冷却机制   ││跨渠道同步   │       │
│  └──────────┘└──────────┘└──────────┘└──────────┘└────────────┘       │
│         │           │           │           │           │               │
│         ▼           ▼           ▼           ▼           ▼               │
│  ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌────────────┐       │
│  │ 执行层   ││ 交付层   ││ 后台任务  ││ 配置系统  ││ 可观测性   │       │
│  │ (V2 新增) ││ (V2 新增) ││ (V1 已有) ││ (V1 已有) ││ (V2 升级)  │       │
│  │          ││          ││          ││          ││            │       │
│  │BSupervisor││ResultVerifier││事件驱动   ││Pydantic   ││日志+指标   │       │
│  │GoalAnchor ││ReportGenerator││对话后维护  ││Schema验证  ││Prometheus  │       │
│  │ToolRegistry││ConfirmMgr││          ││          ││            │       │
│  │SnapshotMgr││          ││          ││          ││            │       │
│  │SubAgentMgr││          ││          ││          ││            │       │
│  └──────────┘└──────────┘└──────────┘└──────────┘└────────────┘       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 V2 模块清单

| 模块 | 职责 | V1 | V2 | 设计文档 |
|------|------|----|----|---------|
| 入口系统 | CLI + 库双模式 | ✅ | — | DESIGN.md §二 |
| Agent 主循环 | 7 步循环 + 状态机 | ✅ | 升级（触发器 + 进入/退出动作 + 并发消息处理 + 状态持久化） | 06_状态机设计.md |
| 记忆系统 | 三层记忆 + 存储抽象 | ✅ | 升级（7种人格算法 + 参数不写死 + get_personality/search接口） | 01_记忆系统全局设计.md |
| 理解层 | 意图解析 + 追问 | ⚠️ | 升级（双锚点+10算法+幂律裁剪 + CompressResult + 参数不写死） | 02_理解层设计.md |
| 上下文压缩 | 双锚点+10算法融合评分+幂律裁剪 | ✅ 完成 | 升级（双锚点保边+10算法评分+幂律裁剪 + CompressResult 9字段） | 09_上下文压缩引擎v1.3.md |
| 安全审批 | 输入过滤 + 冲突检测 + 审批 | ✅ 基础 | 升级（SecurityGuard + ApprovalModule + ConflictChecker + CredentialPool） | 05_安全与治理设计.md |
| LLM 管理 | 多模型路由 + Prompt管理 | ✅ | 新增（ModelRouter回退链 + PromptManager Thompson Sampling + UI接口） | 07_LLM管理设计.md |
| 执行层 | 任务调度 + 工具调用 | ✅ | 新增（BSupervisor + GoalAnchor + ToolRegistry + SnapshotManager + SubAgentManager + ProcessStandard） | 03_执行层设计.md |
| 交付层 | 三级验证 + 报告生成 | ✅ | 新增（ResultVerifier + ReportGenerator + ConfirmationManager） | 04_交付层设计.md |
| 会话管理 | 跨渠道 + 任务同步 | ✅ | 新增（SessionManager + IdentityManager + EventBus） | 08_会话管理设计.md |

---

## 三、上下文压缩引擎（V2 实现）

> **设计来源**：`09_上下文压缩引擎v1.3.md`
>
> **现状**：✅ 已完成。双锚点保边 + 10算法融合评分 + 幂律裁剪，代码 ~757 行。
>
> **架构**：`compress()` 主路径调用 `score_memory`（10算法融合评分）和 `apply_power_law_pruning`（幂律裁剪），无独立 V1 代码。

### 3.1 核心接口

```python
# src/context/compressor.py

@dataclass
class CompressResult:
    "V2 压缩结果（10字段）"
    summary: str = ""                    # 压缩后的摘要文本
    quality_score: float = 0.0           # LLM 自评摘要质量 (0-1)
    pruned_count: int = 0                # 裁剪掉的消息数
    kept_indices: list = field(default_factory=list)  # 保留的消息索引
    compressed_token_count: int = 0      # 节省的 token 数
    method: str = ""                     # 使用的压缩方法
    feedback_signals: dict = field(default_factory=dict)  # 反馈信号
    original_count: int = 0              # 压缩前消息总数（兼容字段）
    kept_ids: list = field(default_factory=list)  # 保留的消息ID列表（兼容字段）
    compressed_count: int = 0            # 压缩后保留的消息数（兼容字段）
```

```python
# src/context/compressor.py

class ContextCompressor:
    """
    上下文压缩器 — 双锚点保边 + 10算法融合评分 + 幂律裁剪

    流程：
    1. 双锚点保边：保留最早M条锚点 + 最近N条工作记忆（信息熵驱动）
    2. 中间区域评分：10算法融合评分引擎（score_memory）
    3. 幂律裁剪：apply_power_law_pruning 裁剪低价值消息

    所有参数不写死，由公式/LLM/用户互动三个维度获得。

    被以下模块调用：
    - loop/agent_loop.py：AgentLoop._step_perceive()
    - session/session_manager.py：SessionManager.on_message()
    """

    def __init__(self, initial_keep: int = 200, compression_threshold: float = 0.6,
                 adjustment_interval: int = 100):
        ...

    async def compress(self, messages: list[dict], current_input: str = "",
                       max_messages: int = None) -> CompressResult:
        """双锚点保边 → 10算法评分 → 幂律裁剪"""
        ...
```

### 3.2 10算法评分引擎

| # | 方法名 | 评分维度 | 科学依据 |
|---|--------|----------|----------|
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

权重公式：`w_i = conf_i / Σconf_j`（置信度归一化）

### 3.3 双锚点策略（DualAnchorStrategy）

- `is_anchor(msg)`：判断消息是否为不可压缩锚点（第一条用户消息 OR 含实体关键词 OR 来自 user/assistant 角色）
- `count_anchors(messages)`：计算锚点消息数 M
- `calc_recent_window(messages)`：计算最近保留窗口 N（信息熵驱动）

### 3.4 后台压缩进程（BackgroundCompressor）

- 状态机：SLEEP → COMPRESSING → MONITORING → SLEEP
- `signal_maybe_compress(session)`：非阻塞检查，超过阈值触发后台压缩
- 分批压缩，零阻塞对话路径

### 3.5 反馈引擎（FeedbackEngine）

- 5类信号：compression_loss / topic_drift / entity_loss / contradiction_introduced / user_correction
- 驱动 α 自适应调整：`α_{t+1} = α_t × (1 + λ × quality_feedback)`

### 3.6 代码差异

| 组件 | V1 代码 | V2 实际 | 行数 |
|------|---------|---------|------|
| `context/compressor.py` | `CompressionResult` + 3算法串行（已删除） | `CompressResult` 10字段 + 双锚点 + 10算法评分 + 幂律裁剪 | ~757 |
| V1 `CompressionResult` | ✅ 保留（向后兼容） | 已删除（统一为 CompressResult） | — |
| `_apply_forgetting_curve` | V1 独立实现 | 已删除（由 `_score_forgetting` + `_score_recency` 替代） | — |
| `_apply_changepoint_detection` | V1 独立实现 | 已删除（由 `_score_topic_consistency` + `_score_contradiction` 替代） | — |
| `_apply_budget` | V1 独立实现 | 已删除（由 `apply_power_law_pruning` 替代） | — |

---

## 四、执行层（V2 新增）

> **设计来源**：`03_执行层设计.md`（2026-05-03 深度融合版）

### 4.1 架构

```
┌─────────────────────────────────────────────────────────┐
│                    执行层                                 │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ BSupervisor  │  │ GoalAnchor   │  │ ToolRegistry │  │
│  │ 任务监督器    │  │ 目标锚定器    │  │ 工具注册表    │  │
│  │              │  │              │  │              │  │
│  │ PID协调      │  │ 多维度偏离度  │  │ 三级沙箱     │  │
│  │ 步骤编排     │  │ 动态阈值     │  │ 工具注册     │  │
│  │ 错误恢复     │  │ 四级纠偏     │  │ 参数验证     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │            │
│         └────────┬────────┴────────┬────────┘            │
│                  ▼                 ▼                      │
│         ┌──────────────┐  ┌──────────────┐              │
│         │ SnapshotManager│ │ SubAgentMgr  │              │
│         │ 快照管理器     │  │ 子Agent管理器 │              │
│         │              │  │              │              │
│         │ WAL原理      │  │ 主/子分离    │              │
│         │ 每步快照     │  │ 进程内通信   │              │
│         │ 失败恢复     │  │ 并发控制     │              │
│         └──────────────┘  └──────────────┘              │
│                                                          │
│  ┌──────────────┐                                        │
│  │ ProcessStandard│                                       │
│  │ 流程标准化器   │                                       │
│  │              │                                        │
│  │ 记录标准步骤  │                                        │
│  │ 积累审批历史  │                                        │
│  └──────────────┘                                        │
└─────────────────────────────────────────────────────────┘
```

### 4.2 BSupervisor — 执行监督器

```python
# src/execution/b_supervisor.py

class BSupervisor:
    """
    执行监督器 — 基于 PID 控制器原理

    科学依据：PID 控制器（控制论）
    - P（比例）：当前偏差 → 立即纠偏
    - I（积分）：累积偏差 → 消除稳态误差
    - D（微分）：偏差变化率 → 预测未来趋势

    所有参数不写死：
    - max_steps: 由 LLM 根据任务复杂度动态评估
    - PID 参数 kp/ki/kd: 由 Ziegler-Nichols 方法在线整定
    """

    def __init__(self, goal_anchor: "GoalAnchor",
                 snapshot_manager: "SnapshotManager",
                 tool_registry: "ToolRegistry",
                 max_steps: int = None):
        self.goal_anchor = goal_anchor
        self.snapshot_manager = snapshot_manager
        self.tool_registry = tool_registry
        # max_steps 不写死，由 LLM 动态评估
        # 参考值：约 7 个子任务 × 7 步/子任务 = 50
        self.max_steps = max_steps
        # PID 参数不写死，由 Ziegler-Nichols 方法在线整定
        self._kp = None
        self._ki = None
        self._kd = None

    async def execute(self, intent, plan,
                      step_callback: Callable = None) -> ExecutionResult:
        """
        执行任务（核心入口）

        流程：
        1. 拆解任务 → 步骤序列
        2. 逐步执行（PID 控制循环）：快照 → 工具 → 锚定 → PID
        3. 全部完成 → 触发交付层
        """
        task_id = getattr(intent, 'id', str(uuid.uuid4())[:8])
        steps = self._decompose(intent, plan)

        if not steps:
            return ExecutionResult(task_id=task_id, status=ExecutionStatus.REJECTED,
                                   error="无法拆解任务")

        max_steps = self.max_steps or 50
        if len(steps) > max_steps:
            return ExecutionResult(task_id=task_id, status=ExecutionStatus.REJECTED,
                                   error=f"任务步骤过多（{len(steps)} > {max_steps}）")

        result = ExecutionResult(task_id=task_id, status=ExecutionStatus.RUNNING,
                                  steps_total=len(steps), started_at=datetime.now())

        for i, step in enumerate(steps):
            step.index = i
            step.status = StepStatus.RUNNING

            # 2a. 保存快照
            self.snapshot_manager.save_snapshot(task_id=task_id, step_index=i,
                state={"current_step": i, "total_steps": len(steps)})

            # 2b. 执行工具
            tool_result = await self.tool_registry.execute(
                tool_name=step.tool_name, params=step.tool_params)
            if tool_result.success:
                step.result = tool_result.output
                step.status = StepStatus.COMPLETED
                result.steps_completed = i + 1
            else:
                step.status = StepStatus.FAILED
                result.status = ExecutionStatus.FAILED
                result.error = f"步骤 {i+1} 失败: {tool_result.error}"
                return result

            # 2c. 目标锚定检查
            deliverable = getattr(plan, 'deliverable_description', '')
            if deliverable:
                anchor_result = self.goal_anchor.check(
                    goal=deliverable,
                    current=f"{step.description}\n{step.result}",
                    progress=i / len(steps))
                if anchor_result.action == "stop":
                    result.status = ExecutionStatus.FAILED
                    result.error = f"严重偏离目标: {anchor_result.suggestion}"
                    return result

        result.status = ExecutionStatus.COMPLETED
        result.completed_at = datetime.now()
        self.snapshot_manager.delete_task_snapshots(task_id)
        return result
```

### 4.3 GoalAnchor — 目标锚定器

```python
# src/execution/goal_anchor.py

@dataclass
class AnchorResult:
    """锚定检查结果"""
    similarity: float = 0.0
    deviation: float = 0.0
    deviation_vector: dict = field(default_factory=dict)
    dynamic_threshold: float = 0.5
    is_on_track: bool = True
    action: str = "continue"       # continue / correct / ask_user / stop
    suggestion: str = ""
    details: dict = field(default_factory=dict)


class GoalAnchor:
    """
    目标锚定器 — 多维度偏离度向量 + 动态阈值 + 四级纠偏

    科学依据：
    - 余弦相似度（方向）：TF-IDF 向量空间模型
    - Levenshtein 编辑距离（结构）：Levenshtein (1966)
    - Jaccard 相似度（意图）：Jaccard (1901)
    - 动态阈值：课程学习（Curriculum Learning, Bengio et al., 2009）

    所有参数不写死：
    - base_threshold: 由 LLM 根据任务类型动态评估
    - PID 参数: 由 Ziegler-Nichols 方法在线整定
    - 纠偏动作阈值: 由 LLM 根据任务风险等级动态调整
    """

    def __init__(self, base_threshold: float = None):
        self.base_threshold = base_threshold  # None 表示由 LLM 动态评估
        self._history = []
        self._kp = None
        self._ki = None
        self._kd = None

    def get_dynamic_threshold(self, progress: float) -> float:
        """
        计算动态阈值：threshold = base + 0.4 × progress²

        - progress = 0.0 → threshold = base（宽松，允许探索）
        - progress = 0.5 → threshold = base + 0.1（逐步收紧）
        - progress = 1.0 → threshold = base + 0.4（严格，确保交付物与目标一致）

        base 值由 LLM 根据任务类型动态评估，不写死。
        """
        base = self.base_threshold if self.base_threshold is not None else 0.5
        return base + 0.4 * (progress ** 2)

    def check(self, goal: str, current: str,
              progress: float = 0.0) -> AnchorResult:
        """
        检查当前状态是否偏离目标

        综合偏离度 = cosine_deviation × 0.4 + edit_deviation × 0.3 + semantic_deviation × 0.3

        四级纠偏：
        🟢 continue：在轨，继续执行
        🟡 correct：轻微偏离，PID纠偏
        🟠 ask_user：中度偏离，请求用户确认
        🔴 stop：严重偏离，停止执行

        纠偏动作阈值由 LLM 根据任务风险等级动态调整，不写死。
        """
        cosine_sim = self._cosine_similarity(goal, current)
        edit_dist = self._levenshtein_normalized(goal, current)
        jaccard_sim = self._jaccard_similarity(goal, current)

        deviation_vector = {
            "cosine": 1 - cosine_sim,
            "edit": edit_dist,
            "semantic": 1 - jaccard_sim,
        }
        deviation = (deviation_vector["cosine"] * 0.4 +
                     deviation_vector["edit"] * 0.3 +
                     deviation_vector["semantic"] * 0.3)
        similarity = 1 - deviation
        dynamic_threshold = self.get_dynamic_threshold(progress)
        is_on_track = similarity >= dynamic_threshold

        # 四级纠偏动作（阈值由 LLM 动态调整）
        if is_on_track:
            action, suggestion = "continue", "当前执行方向正确"
        elif deviation < 0.5:
            action, suggestion = "correct", "轻微偏离目标，PID纠偏"
        elif deviation < 0.7:
            action, suggestion = "ask_user", "中度偏离目标，请求用户确认"
        else:
            action, suggestion = "stop", "严重偏离目标！停止当前操作"

        return AnchorResult(
            similarity=round(similarity, 3),
            deviation=round(deviation, 3),
            deviation_vector=deviation_vector,
            dynamic_threshold=round(dynamic_threshold, 3),
            is_on_track=is_on_track,
            action=action,
            suggestion=suggestion,
        )
```

### 4.4 ToolRegistry — 工具注册表

```python
# src/execution/tool_registry.py

class ToolLevel(Enum):
    """工具沙箱等级（由 LLM 根据操作类型动态评估，不硬编码固定分级）"""
    L1_SAFE = 1       # 安全工具：直接执行
    L2_CONFIRM = 2    # 需确认工具：执行前确认
    L3_APPROVE = 3    # 需审批工具：执行前审批


class ToolRegistry:
    """
    工具注册表 + 三级沙箱

    科学依据：操作系统 Ring 保护环 + 风险评估矩阵

    设计原则：
    - 工具即数据（配置驱动，不改代码）
    - 所有工具的风险等级由 LLM 根据操作类型、影响范围、可逆性动态评估
    - 未注册的工具不可调用
    """

    def register(self, name: str, description: str, level: ToolLevel,
                 handler: Callable, parameters: dict = None): ...

    async def execute(self, tool_name: str, params: dict,
                      approval_callback: Callable = None) -> ToolResult: ...
```

### 4.5 SnapshotManager — 快照管理器

```python
# src/execution/snapshot_manager.py

class SnapshotManager:
    """
    快照管理器 — 基于 WAL 原理

    科学依据：数据库 WAL（Write-Ahead Log）
    - 执行前记录 → 失败可恢复
    - 执行后标记 → 成功可确认

    所有参数不写死：
    - max_snapshots: 由 LLM 根据任务复杂度和存储容量动态评估
    - snapshot_dir: 由用户配置或 LLM 根据项目结构确定
    """

    def __init__(self, snapshot_dir: str = None, max_snapshots: int = None):
        self.snapshot_dir = snapshot_dir or "./snapshots"
        self.max_snapshots = max_snapshots  # None 表示由 LLM 动态评估
        self._snapshots = {}

    def save_snapshot(self, task_id: str, step_index: int, state: dict) -> TaskSnapshot: ...

    def get_latest_snapshot(self, task_id: str) -> Optional[TaskSnapshot]: ...

    def restore_from_snapshot(self, task_id: str) -> dict: ...

    def delete_task_snapshots(self, task_id: str): ...
```

### 4.6 SubAgentManager — 子 Agent 管理器

```python
# src/execution/sub_agent_manager.py

class SubAgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PENDING_CONFIRMATION = "pending_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class SubAgentManager:
    """
    子 Agent 管理器

    设计要点：
    1. 主 Agent 只分配，不执行
    2. 子 Agent 用完即销毁
    3. 进程内通信（asyncio，不走网络）
    4. 并发控制（最大并发数限制）
    5. 失败隔离（一个子 Agent 失败不影响其他）
    6. 确认机制（执行完成 ≠ 结束，用户确认后才销毁）

    所有参数不写死：
    - max_concurrent: 由 LLM 根据系统资源动态评估
    - timeout_seconds: 由 LLM 根据任务复杂度动态评估
    """

    def __init__(self, tool_system=None, llm_fn=None,
                 approval_gate=None, max_concurrent: int = None):
        self.tool_system = tool_system
        self.llm_fn = llm_fn
        self.approval_gate = approval_gate
        # max_concurrent 不写死，由 LLM 动态评估
        self.max_concurrent = max_concurrent
        self._running: dict[str, SubAgent] = {}
        self._history: list[SubAgent] = []

    async def spawn(self, task: SubAgentTask) -> SubAgent: ...

    async def wait(self, subagent_id: str, timeout: int = None) -> Optional[SubAgent]: ...

    async def cancel(self, subagent_id: str) -> bool: ...
```

### 4.7 ProcessStandard — 流程标准化

```python
# src/execution/process_standard.py

class ProcessStandard:
    """
    流程标准化器

    职责：
    1. 记录每次任务的标准步骤
    2. 积累审批记录，形成标准流程指南
    3. 指导未来类似任务

    设计原则：
    - 每次审批通过的操作都在积累"什么样的操作需要审批"
    - 项目结束后可以回顾完整的审批记录
    - 形成标准流程指南，指导未来类似任务
    """

    def __init__(self, memory_manager):
        self.memory = memory_manager
        self._standard_processes: dict[str, list] = {}

    def record_step(self, task_type: str, step: dict): ...

    def get_standard_process(self, task_type: str) -> list: ...

    def finalize_task(self, task_type: str, step_log: list, approval_log: list): ...
```

---

## 五、交付层（V2 新增）

> **设计来源**：`04_交付层设计.md`（2026-05-03 深度融合版）

### 5.1 架构

```
┌─────────────────────────────────────────────────────────┐
│                    交付层                                 │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────┐           │
│  │ ResultVerifier   │    │ ReportGenerator  │           │
│  │ 结果验证器        │    │ 报告生成器        │           │
│  │                  │    │                  │           │
│  │ L1: 静态检查     │    │ 金字塔原理       │           │
│  │ L2: 动态测试     │    │ 分层报告         │           │
│  │ L3: 人工确认     │    │ 证据链           │           │
│  │                  │    │ 渐进式披露       │           │
│  │ 风险自适应阈值   │    │                  │           │
│  │ 自适应覆盖率     │    │                  │           │
│  └──────────────────┘    └──────────────────┘           │
│                                                          │
│  ┌──────────────────┐                                    │
│  │ ConfirmationMgr  │                                    │
│  │ 任务确认管理器    │                                    │
│  │                  │                                    │
│  │ 用户确认         │                                    │
│  │ 标准报告         │                                    │
│  │ 流程标准化       │                                    │
│  └──────────────────┘                                    │
└─────────────────────────────────────────────────────────┘
```

### 5.2 ResultVerifier — 结果验证器

```python
# src/delivery/result_verifier.py

class VerificationLevel(Enum):
    """验证级别"""
    L1_STATIC = 1       # 静态检查
    L2_DYNAMIC = 2      # 动态测试
    L3_MANUAL = 3       # 人工确认


class VerificationStatus(Enum):
    """验证状态"""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class VerificationItem:
    """一条验证结果"""
    criterion: str = ""
    level: VerificationLevel = VerificationLevel.L1_STATIC
    status: VerificationStatus = VerificationStatus.SKIPPED
    evidence: str = ""
    error: str = ""
    duration: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class VerificationReport:
    """验证报告"""
    task_id: str = ""
    intent_id: str = ""
    overall_status: VerificationStatus = VerificationStatus.SKIPPED
    items: list = field(default_factory=list)
    summary: str = ""
    evidence_chain: list = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    id: str = ""

    @property
    def pass_rate(self) -> float:
        completed = [i for i in self.items
                     if i.status in (VerificationStatus.PASSED, VerificationStatus.FAILED)]
        if not completed:
            return 0.0
        return sum(1 for i in completed if i.status == VerificationStatus.PASSED) / len(completed)


class ResultVerifier:
    """
    结果验证器 — 三级验证 + 风险自适应阈值

    科学依据：
    1. 软件测试金字塔：L1(静态) → L2(动态) → L3(人工)
    2. 统计学假设检验：H0=不达标，通过→拒绝H0
    3. 风险自适应测试（Risk-Based Testing, Amland, 2002）

    所有参数不写死：
    - 风险等级阈值由 LLM 根据任务描述动态评估
    - 通过率阈值由风险等级动态确定
    - 自适应覆盖率阈值由统计学置信区间理论计算
    """

    def __init__(self, default_pass_rate: float = None):
        self.default_pass_rate = default_pass_rate  # None 表示由 LLM 动态评估

    def _assess_risk_level(self, task_description: str, context: dict = None) -> str:
        """
        评估风险等级（由 LLM 动态评估）
        评估维度：影响范围、可逆性、数据敏感性、用户数量
        """
        # 实际实现中调用 LLM
        ...

    def _get_pass_rate_threshold(self, risk_level: str) -> float:
        """
        根据风险等级获取通过率阈值
        阈值不写死，由 LLM 根据用户历史数据动态调整。
        参考范围：低风险 0.70 / 中风险 0.85 / 高风险 0.95
        """
        thresholds = {"low": 0.70, "medium": 0.85, "high": 0.95}
        return thresholds.get(risk_level, self.default_pass_rate or 0.85)

    async def verify(self, execution_result, deliverable_plan) -> VerificationReport:
        """
        验证执行结果（核心入口）
        流程：L1 静态检查 → L2 动态测试 → 综合判断（风险自适应阈值）→ 构建证据链
        """
        ...
```

### 5.3 ReportGenerator — 报告生成器

```python
# src/delivery/report_generator.py

@dataclass
class DeliveryReport:
    """交付报告 — 分层设计（金字塔原理 + 渐进式披露）"""
    task_id: str = ""
    conclusion: str = ""                # 一句话结论
    summary: str = ""                   # 3-5句话概括
    details: list = field(default_factory=list)      # 完整证据链
    suggestions: list = field(default_factory=list)  # 改进建议
    risks: list = field(default_factory=list)        # 风险提示
    evidence_chain: list = field(default_factory=list)
    deviation_history: list = field(default_factory=list)     # 偏离历史
    compression_record: dict = field(default_factory=dict)    # 压缩记录
    compression_lessons: list = field(default_factory=list)   # 压缩教训
    user_summary: dict = field(default_factory=dict)  # 用户摘要层
    tech_detail: dict = field(default_factory=dict)   # 技术详情层
    active_layer: str = "summary"
    created_at: datetime = field(default_factory=datetime.now)


class ReportGenerator:
    """
    报告生成器 — 金字塔原理 + 分层报告

    设计原则：
    - 结论 → 总结 → 细节（金字塔原理）
    - 用户摘要层（默认展示）+ 技术详情层（点击展开）
    - 宁可说"没做完"，也不说"做完了"但有问题
    """

    def generate(self, verification_report, execution_result=None,
                 compression_record: dict = None, lessons: list = None) -> DeliveryReport: ...
```

### 5.4 ConfirmationManager — 任务确认管理器

```python
# src/delivery/report_generator.py（与 ReportGenerator 同文件）

class ConfirmationStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ISSUE_FOUND = "issue_found"
    ROLLED_BACK = "rolled_back"
    TIMEOUT = "timeout"


class ConfirmationManager:
    """
    任务确认管理器

    核心理念：执行完成 ≠ 真正结束
    - 执行层完成所有步骤 → 交付层验证通过 → 用户确认实际结果没问题 → 真正结束

    所有参数不写死：
    - timeout_seconds: 由 LLM 根据任务复杂度和用户响应习惯动态评估
    """

    def __init__(self, notify_fn=None, memory_manager=None):
        self.notify_fn = notify_fn
        self.memory = memory_manager
        self._pending: dict[str, TaskConfirmation] = {}
        self._history: list[TaskConfirmation] = []

    async def request_confirmation(self, task_id, task_title,
                                     execution_result, step_log, **kwargs) -> TaskConfirmation: ...

    async def handle_user_response(self, confirmation_id: str, response: str) -> TaskConfirmation: ...
```

---

## 六、安全审批模块（V2 新增）

> **设计来源**：`05_安全与治理设计.md`（2026-05-03 深度融合版）

### 6.1 架构

```
┌─────────────────────────────────────────────────────────┐
│                  安全与治理层                             │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  SecurityGuard（安全防护）                         │   │
│  │  第一道防线：过滤所有输入/输出/路径                 │   │
│  │  多层过滤（输入/路径/输出）                        │   │
│  │  检测模式由 LLM 定期更新，不硬编码                 │   │
│  └──────────────────────────────────────────────────┘   │
│                          │                               │
│  ┌──────────────────────▼───────────────────────────┐   │
│  │  ApprovalModule（审批模块）                        │   │
│  │  第二道防线：危险操作必须审批                       │   │
│  │  L1 自动通过 │ L2 确认后执行 │ L3 强制审批        │   │
│  │  风险评分由 LLM 动态评估                           │   │
│  │  超时时间由公式动态计算                            │   │
│  └──────────────────────────────────────────────────┘   │
│                          │                               │
│  ┌──────────────────────▼───────────────────────────┐   │
│  │  ConflictChecker（冲突检测器）                     │   │
│  │  第三道防线：写入记忆前检测知识冲突                 │   │
│  │  Jaccard 粗筛 + LLM 语义分析精判                  │   │
│  │  冲突阈值由 LLM 动态调整                           │   │
│  └──────────────────────────────────────────────────┘   │
│                          │                               │
│  ┌──────────────────────▼───────────────────────────┐   │
│  │  CredentialPool（凭证池）                          │   │
│  │  基础保障：所有凭证加密存储                         │   │
│  │  AES-256-GCM 加密 + 轮换策略 + 冷却机制           │   │
│  │  密钥由用户密码 PBKDF2 派生，不硬编码              │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 6.2 SecurityGuard — 安全防护

```python
# src/security/guard.py

@dataclass
class SecurityCheckResult:
    """安全检查结果"""
    is_safe: bool
    threat_type: str
    description: str
    original_input: str
    sanitized_input: str = ""


class SecurityGuard:
    """
    安全防护 — 多层过滤

    防护层：
    1. 输入过滤：提示词注入检测
    2. 路径检查：路径遍历防护
    3. 输出检查：敏感信息泄露检测

    所有检测模式不写死，由 LLM 根据最新攻击手段动态更新。
    """

    def check_input(self, user_input: str) -> SecurityCheckResult: ...

    def check_path(self, path: str) -> SecurityCheckResult: ...

    def check_output(self, output: str) -> SecurityCheckResult: ...
```

### 6.3 ApprovalModule — 审批模块

```python
# src/security/guard.py（ApprovalModule 合并在内）

class ApprovalModule:
    """
    审批模块 — 三级协商 + 自适应超时

    设计原则：
    - 风险评分由 LLM 动态评估，不写死
    - 超时时间由公式动态计算，不写死
    - 审批是强制卡点，不是建议
    - 所有审批记录永久保存，可追溯

    超时公式：timeout = base_timeout × (1 + risk_score) / (1 + urgency_score)
    - base_timeout 由 LLM 根据用户响应习惯动态调整
    - risk_score ∈ [0, 1]（LLM 动态评估）
    - urgency_score ∈ [0, 1]（操作紧急程度）
    """

    def evaluate_risk(self, action: str, params: dict) -> dict:
        """评估操作风险 — LLM 动态评估"""
        ...

    def calculate_timeout(self, risk_score: float,
                          urgency_score: float = 0.5) -> float:
        """计算自适应超时时间"""
        ...

    async def request_approval(self, action: str, params: dict,
                               user_callback: Callable = None,
                               urgency_score: float = 0.5,
                               timeout_policy: str = "pause") -> ApprovalRequest: ...

    def approve(self, request_id: str, approver: str = "user"): ...

    def reject(self, request_id: str, approver: str = "user"): ...
```

### 6.4 ConflictChecker — 冲突检测器

```python
# src/security/guard.py（ConflictChecker 合并在内）

class ConflictChecker:
    """
    冲突检测器 — 两阶段检测（自指性理论）

    阶段1 — Jaccard 相似度粗筛：
      Jaccard(new, existing) > 阈值 → 进入阶段2
      阈值不写死，由 LLM 根据知识库特征动态确定

    阶段2 — LLM 语义分析精判：
      LLM 综合评估两条知识的语义关系
      输出：conflict_probability ∈ [0, 1]
      conflict_probability > 0.7 → 直接冲突
      0.4 < conflict_probability ≤ 0.7 → 潜在矛盾
    """

    def __init__(self, jaccard_threshold: float = None):
        self.jaccard_threshold = jaccard_threshold  # None 表示由 LLM 动态确定

    def check(self, new_knowledge: str,
              existing_knowledge: list[str]) -> list[Conflict]: ...

    def _llm_analyze_conflict(self, knowledge_a: str, knowledge_b: str) -> float:
        """LLM 语义分析冲突（实际实现中调用 LLM）"""
        ...
```

### 6.5 CredentialPool — 凭证池

```python
# src/security/guard.py（CredentialPool 合并在内）

class CredentialPool:
    """
    凭证池 — AES-256-GCM 加密存储 + 轮换策略

    设计原则：
    - 所有凭证加密存储，不硬编码
    - 支持多凭证轮换
    - 限流冷却机制
    - 密钥来源：用户密码 PBKDF2 派生（迭代次数 100,000，OWASP 推荐）
    - 盐值随机生成，安全存储（盐值丢失 = 所有凭证无法解密）
    """

    def __init__(self, storage_path: str = None,
                 rotation_strategy: str = None):
        # storage_path 不写死，由用户配置或 LLM 动态确定
        # rotation_strategy 不写死，由用户配置
        ...

    def set_master_key(self, password: str):
        """设置主密钥（从用户密码 PBKDF2 派生）"""
        ...

    def add_credential(self, name: str, value: str): ...

    def get_credential(self, name: str) -> Optional[str]: ...

    def cooldown(self, name: str, duration_seconds: int = None):
        """
        将凭证设为冷却状态
        duration_seconds 不写死，由 LLM 根据限流响应头动态评估
        """
        ...
```

---

## 七、LLM 管理（V2 新增）

> **设计来源**：`07_LLM管理设计.md`（2026-05-03 深度融合版）

### 7.1 架构

```
┌─────────────────────────────────────────────────────────┐
│                    LLM 管理                              │
│                                                          │
│  ┌──────────────────┐    ┌──────────────────┐           │
│  │ ModelRouter      │    │ PromptManager    │           │
│  │ 模型路由器        │    │ 提示词管理器      │           │
│  │                  │    │                  │           │
│  │ 注册模型         │    │ Prompt 模板管理  │           │
│  │ 回退链自动切换   │    │ A/B 测试         │           │
│  │ 冷却机制         │    │ Thompson Sampling│           │
│  │ 暴露状态给 UI    │    │ 质量评分         │           │
│  │                  │    │                  │           │
│  │ 不做任务分级路由 │    │ 参数不写死       │           │
│  │ 不考虑成本优化   │    │                  │           │
│  └──────────────────┘    └──────────────────┘           │
│                                                          │
│  支持：OpenAI / Anthropic / Google / 本地 Ollama        │
│  配置：用户提供 Key + 模型名称 + 端点                     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 7.2 ModelRouter — 模型路由器

```python
# src/llm/model_router.py

class ModelRouter:
    """
    模型路由器 — 回退链 + 冷却机制 + UI 接口

    设计原则（LLM管理极简）：
    - 不做任务分级路由
    - 用户选什么模型就用什么
    - 只提供切换接口
    - 不考虑多模型回退场景（保留回退链但简化）
    - 所有参数不写死
    """

    def __init__(self):
        self._models: list[ModelConfig] = []
        self._current_index: int = 0
        self._cooldowns: dict[str, datetime] = {}

    def register_model(self, name: str, provider: str, model: str,
                       api_key: str, base_url: str = None,
                       priority: int = None):
        """
        注册一个模型
        priority 不写死，由用户指定或 LLM 根据模型能力动态评估
        """
        ...

    def get_status(self) -> dict:
        """
        获取当前模型状态（供 UI 显示）
        返回：当前模型、回退链、冷却状态
        """
        ...

    def switch_model(self, name: str):
        """手动切换模型"""
        ...

    async def call(self, prompt: str, **kwargs) -> str:
        """
        调用 LLM（带回退链 + 冷却检查）
        冷却时长不写死，由 LLM 根据限流响应头动态评估
        """
        ...

    def cooldown(self, model_name: str, duration_seconds: int = None):
        """
        将模型设为冷却状态
        duration_seconds 不写死，由 LLM 动态评估
        """
        ...
```

### 7.3 PromptManager — 提示词管理器

```python
# src/llm/prompt_manager.py

class PromptManager:
    """
    提示词管理器 — A/B 测试 + Thompson Sampling

    设计原则：
    - Prompt 模板由 LLM 动态生成，不硬编码
    - 质量评分学习率由评分波动性动态调整，不写死
    - Thompson Sampling 权重由用户反馈动态调整
    """

    def __init__(self):
        self._templates: dict[str, list[PromptTemplate]] = {}
        # Thompson Sampling 权重不写死，由用户反馈动态调整
        self._ts_weights: dict[str, tuple[float, float]] = {}

    def register_template(self, task_type: str, template: str,
                          variant: str = "default"): ...

    def render_prompt(self, task_type: str, variables: dict) -> str:
        """
        渲染 Prompt 模板（Thompson Sampling 选择最优变体）
        """
        ...

    def record_feedback(self, task_type: str, variant: str, quality: float):
        """记录质量反馈（用于 Thompson Sampling 更新）"""
        ...
```

---

## 八、会话管理（V2 新增）

> **设计来源**：`08_会话管理设计.md`（2026-05-03 深度融合版）

### 8.1 架构

```
用户消息（任意渠道）
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        SessionManager                                │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  统一身份层（IdentityManager）                                 │   │
│  │  · 渠道 user_id → universal_id 映射                           │   │
│  │  · 主动关联（用户验证绑定）                                    │   │
│  │  · 自动匹配（邮箱/手机号/用户名相似度）                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  会话生命周期                                                  │   │
│  │  · 创建/获取会话（基于 universal_id）                          │   │
│  │  · 加载上下文（每次消息）                                      │   │
│  │  · 追加消息 + 压缩触发判断                                     │   │
│  │  · 压缩上下文（ContextCompressor 双锚点+10算法+幂律裁剪）                      │   │
│  │  · 归档会话（长期不活跃）                                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  任务状态同步（事件驱动）                                       │   │
│  │  · 订阅 event_bus 事件                                        │   │
│  │  · agent_status_changed → 更新任务状态                        │   │
│  │  · 状态变更 → 同步到第2层核心记忆                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  跨渠道管理                                                    │   │
│  │  · 渠道适配（webchat/飞书/钉钉/Telegram）                      │   │
│  │  · 渠道特定格式转换                                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
         │                           │
         ▼                           ▼
┌─────────────────┐     ┌─────────────────────────┐
│ ContextCompressor│     │      EventBus            │
│ · 双锚点+10算法+幂律裁剪 │     │ · 发布/订阅              │
│ · CompressResult 10字段│     │ · 事件路由               │
└─────────────────┘     └─────────────────────────┘
```

### 8.2 SessionManager — 会话管理器

```python
# src/session/session_manager.py

class SessionStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    IDLE = "idle"


@dataclass
class Session:
    """会话"""
    id: str
    universal_id: str
    channel: str
    messages: list = field(default_factory=list)
    context_summary: str = ""
    task_states: dict = field(default_factory=dict)
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class SessionManager:
    """
    会话管理器 — 跨渠道 + 上下文压缩 + 任务状态同步 + 归档

    所有参数不写死：
    - max_messages: 由 LLM 根据上下文窗口大小动态评估
    - compress_threshold: 由 LLM 根据用户对话模式动态评估
    - archive_days: 由 LLM 根据用户使用频率动态评估
    """

    def __init__(self, memory_manager=None, compressor=None, event_bus=None):
        self.memory = memory_manager
        self.compressor = compressor
        self.event_bus = event_bus
        self.identity = IdentityManager()
        self._sessions: dict[str, Session] = {}

    async def on_message(self, channel: str, channel_user_id: str,
                          content: str) -> str:
        """处理来自任意渠道的消息"""
        # 1. 统一身份识别
        universal_id = await self.identity.resolve(channel, channel_user_id)
        # 2. 获取或创建会话
        session = self._get_or_create(universal_id, channel)
        # 3. 追加消息
        session.messages.append({"role": "user", "content": content})
        # 4. 压缩检测（非阻塞）
        if self.compressor:
            result = await self.compressor.compress(session.messages, session.context_summary)
            session.context_summary = result.summary
        # 5. 生成回复
        response = await self._generate_response(session)
        # 6. 追加回复
        session.messages.append({"role": "assistant", "content": response})
        return response
```

### 8.3 IdentityManager — 统一身份管理器

```python
# src/session/identity_manager.py

class IdentityManager:
    """
    统一身份管理器 — 跨渠道身份统一

    职责：
    - 将不同渠道的 user_id 映射到统一的 universal_id
    - 支持主动关联（用户验证绑定）
    - 支持自动匹配（邮箱/手机号/用户名相似度）
    """

    def __init__(self, storage_path: str = None):
        # storage_path 不写死，由用户配置或 LLM 动态确定
        self._storage_path = storage_path or "./data/identities.json"
        self._identity_map: dict[str, str] = {}  # f"{channel}:{user_id}" -> universal_id

    async def resolve(self, channel: str, channel_user_id: str) -> str:
        """解析渠道 user_id → universal_id"""
        key = f"{channel}:{channel_user_id}"
        if key in self._identity_map:
            return self._identity_map[key]
        # 创建新的 universal_id
        universal_id = str(uuid.uuid4())[:12]
        self._identity_map[key] = universal_id
        return universal_id
```

### 8.4 EventBus — 事件总线

```python
# src/session/event_bus.py

class EventBus:
    """
    事件总线 — 发布/订阅 + 事件路由 + 异步处理

    职责：
    - 解耦模块间通信
    - 支持异步事件处理
    - 支持正则路由
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """订阅事件"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    async def publish(self, event_type: str, event: dict = None):
        """发布事件"""
        for callback in self._subscribers.get(event_type, []):
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"事件处理失败: {event_type}, {e}")
```

---

## 九、状态机完善（V2 升级）

> **设计来源**：`06_状态机设计.md`（2026-05-03 深度融合版）
>
> **现状**：V1 已实现 7 状态 + 合法转换表。V2 补充触发器 + 进入/退出动作 + 并发消息处理 + 状态持久化。

### 9.1 状态定义

```python
# src/loop/state.py

class AgentState(Enum):
    """Agent 状态"""
    IDLE = "idle"
    READY = "ready"
    EXECUTING = "executing"
    PAUSED = "paused"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class TransitionTrigger(Enum):
    """状态转换触发器"""
    TASK_RECEIVED = "task_received"
    START_EXECUTION = "start_execution"
    CANCEL = "cancel"
    PAUSE = "pause"
    RESUME = "resume"
    NEED_APPROVAL = "need_approval"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    COMPLETE = "complete"
    FAIL = "fail"
    RETRY = "retry"
    NEW_TASK = "new_task"
```

### 9.2 进入/退出动作

```python
# src/loop/state.py（续）

class AgentStateMachine:
    """
    Agent 状态机 — 有限状态机（FSM）

    设计原则：
    1. 状态转换必须显式声明
    2. 每个状态有明确的进入/退出动作
    3. 非法转换必须拒绝
    4. 状态持久化（支持恢复）
    5. 所有超时参数由公式/LLM/用户互动获得，不写死
    """

    def __init__(self):
        self._transitions = {
            (AgentState.IDLE, TransitionTrigger.TASK_RECEIVED): AgentState.READY,
            (AgentState.READY, TransitionTrigger.START_EXECUTION): AgentState.EXECUTING,
            (AgentState.READY, TransitionTrigger.CANCEL): AgentState.IDLE,
            (AgentState.EXECUTING, TransitionTrigger.PAUSE): AgentState.PAUSED,
            (AgentState.EXECUTING, TransitionTrigger.NEED_APPROVAL): AgentState.WAITING,
            (AgentState.EXECUTING, TransitionTrigger.COMPLETE): AgentState.COMPLETED,
            (AgentState.EXECUTING, TransitionTrigger.FAIL): AgentState.FAILED,
            (AgentState.PAUSED, TransitionTrigger.RESUME): AgentState.EXECUTING,
            (AgentState.PAUSED, TransitionTrigger.CANCEL): AgentState.IDLE,
            (AgentState.WAITING, TransitionTrigger.APPROVAL_GRANTED): AgentState.EXECUTING,
            (AgentState.WAITING, TransitionTrigger.APPROVAL_DENIED): AgentState.FAILED,
            (AgentState.WAITING, TransitionTrigger.APPROVAL_TIMEOUT): AgentState.IDLE,
            (AgentState.COMPLETED, TransitionTrigger.NEW_TASK): AgentState.IDLE,
            (AgentState.FAILED, TransitionTrigger.RETRY): AgentState.EXECUTING,
            (AgentState.FAILED, TransitionTrigger.CANCEL): AgentState.IDLE,
        }
        self._entry_actions = {
            AgentState.READY: self._on_enter_ready,
            AgentState.EXECUTING: self._on_enter_executing,
            AgentState.PAUSED: self._on_enter_paused,
            AgentState.WAITING: self._on_enter_waiting,
            AgentState.COMPLETED: self._on_enter_completed,
            AgentState.FAILED: self._on_enter_failed,
        }
        self._exit_actions = {
            AgentState.EXECUTING: self._on_exit_executing,
            AgentState.PAUSED: self._on_exit_paused,
            AgentState.WAITING: self._on_exit_waiting,
        }
        self._current_state = AgentState.IDLE
        self._transition_history = []

    def can_transition(self, trigger: TransitionTrigger) -> bool:
        """检查是否可以执行某个转换"""
        return (self._current_state, trigger) in self._transitions

    def transition(self, trigger: TransitionTrigger, metadata: dict = None) -> bool:
        """执行状态转换"""
        key = (self._current_state, trigger)
        if key not in self._transitions:
            logger.warning(f"非法状态转换: {self._current_state.value} + {trigger.value}")
            return False
        target_state = self._transitions[key]
        # 执行退出动作
        if self._current_state in self._exit_actions:
            self._exit_actions[self._current_state]()
        # 更新状态
        old_state = self._current_state
        self._current_state = target_state
        self._transition_history.append(StateTransition(
            from_state=old_state, to_state=target_state, trigger=trigger, metadata=metadata or {}))
        # 执行进入动作
        if target_state in self._entry_actions:
            self._entry_actions[target_state]()
        return True

    # === 进入动作 ===
    def _on_enter_ready(self): ...
    def _on_enter_executing(self): ...
    def _on_enter_paused(self): ...
    def _on_enter_waiting(self): ...
    def _on_enter_completed(self): ...
    def _on_enter_failed(self): ...

    # === 退出动作 ===
    def _on_exit_executing(self): ...
    def _on_exit_paused(self): ...
    def _on_exit_waiting(self): ...
```

### 9.3 并发消息处理

```python
# src/loop/state.py（MessageQueue 合并在内）

class MessagePriority:
    """优先级定义（数值不写死，由 LLM 根据业务场景动态调整）"""
    EMERGENCY = 0   # 紧急：系统关闭、强制停止
    CONTROL = 1     # 控制：pause, cancel, resume
    APPROVAL = 2    # 审批：approval_granted, approval_denied
    NORMAL = 3      # 普通：新任务、查询


class MessageQueue:
    """
    Agent 消息队列

    设计原则：
    - 可中断状态的消息立即处理（不进入队列）
    - 不可中断状态的消息按优先级排队
    - 同优先级按时间顺序处理（FIFO）
    """

    # 各状态下允许立即处理的触发器
    INTERRUPTIBLE_TRIGGERS = {
        AgentState.IDLE: "*",
        AgentState.READY: "*",
        AgentState.EXECUTING: {TransitionTrigger.PAUSE, TransitionTrigger.CANCEL},
        AgentState.PAUSED: "*",
        AgentState.WAITING: {
            TransitionTrigger.APPROVAL_GRANTED,
            TransitionTrigger.APPROVAL_DENIED,
            TransitionTrigger.APPROVAL_TIMEOUT,
        },
        AgentState.COMPLETED: "*",
        AgentState.FAILED: "*",
    }

    def __init__(self, state_machine: AgentStateMachine):
        self._queue = []
        self._state_machine = state_machine

    def is_interruptible(self, trigger: TransitionTrigger) -> bool:
        """检查当前状态下该触发器是否可立即处理"""
        current = self._state_machine.current_state
        allowed = self.INTERRUPTIBLE_TRIGGERS.get(current, set())
        if allowed == "*":
            return True
        return trigger in allowed

    def enqueue(self, trigger: TransitionTrigger,
                priority: int = MessagePriority.NORMAL,
                metadata: dict = None) -> bool:
        """处理消息：可中断则立即处理，否则入队排队"""
        ...
```

### 9.4 状态持久化

```python
# src/loop/state.py（StatePersistence 合并在内）

class StatePersistence:
    """
    状态持久化 — SQLite + JSON 双格式

    SQLite 用于需要查询、索引和事务安全的场景。
    JSON 用于轻量级场景（备份、导出）。
    """

    def __init__(self, db_path: str = None):
        # db_path 不写死，由用户配置或 LLM 动态确定
        self.db_path = db_path or "./data/agent_state.db"
        self._init_db()

    def save_snapshot(self, snapshot: StateSnapshot, agent_id: str,
                      timeout_config: dict): ...

    def load_latest_snapshot(self, task_id: str) -> Optional[dict]: ...

    def record_transition(self, transition: StateTransition, agent_id: str): ...

    def record_heartbeat(self, agent_id: str, task_id: str, state: str,
                         interval: int, timeout: Optional[int]): ...
```

---

## 十、人格系统完善（V2 升级）

> **设计来源**：`01_记忆系统全局设计.md` v1.3（2026-05-03 深度融合版）
>
> **现状**：V1 只实现了 PID 控制器（类变量形式）。V2 补全 7 种算法，所有参数不写死。

### 10.1 7 种人格调整算法

```python
# src/memory/personality/

# V2 新增（所有参数不写死）
personality/pid_controller.py           # PID 控制器（Ziegler-Nichols 在线整定）
personality/kalman_filter.py           # 卡尔曼滤波（残差协方差匹配在线估计）
personality/bayesian_update.py         # 贝叶斯推断（用户历史数据确定先验）
personality/reinforcement_learning.py  # 强化学习（奖惩学习）
personality/multi_armed_bandit.py      # 多臂老虎机（UCB1 探索/利用）
personality/fuzzy_controller.py        # 模糊控制（LLM 语义分析，无硬编码规则）
personality/entropy_controller.py      # 信息熵（LLM 动态调整探索阈值）
```

### 10.2 推荐组合方案

```
初期方案（V2 MVP，简单够用）：
  PID 控制器 + 卡尔曼滤波 + 模糊控制

后期方案（V2 完整，更精准）：
  贝叶斯推断（核心）+ 卡尔曼滤波（噪声过滤）+ 强化学习（策略优化）
  + 多臂老虎机（探索/利用平衡）+ 信息熵（自适应探索）
```

### 10.3 更新触发条件

```
自动触发：
  · 每次对话结束 → 第2层压缩 → 提炼到第1层
  · 用户正面/负面反馈 → 相关维度权重调整

  · 同一反馈出现 N 次 → 自动调整
    N 不写死，由 LLM 根据反馈一致性动态评估。
    原理：二项分布显著性检验（Fisher, 1925）。
    LLM 根据最近 k 次反馈的一致性程度，
    计算需要多少次同方向反馈才能拒绝"随机噪声"假设（α=0.05）。

  · 偏差超过阈值 → 立即调整
    阈值不写死，由 LLM 根据历史人格评分波动标准差动态计算。
    阈值 = 历史波动标准差 × 2.5（约 99% 置信区间）

  · 偏差在中间范围 → 缓慢调整（PID 比例带）
  · 偏差在死区内 → 不调整（防止抖动）

手动触发：
  · 用户说"记住这个" → 添加规矩
  · 用户说"xxx 调高/调低" → 直接调整
  · 用户说"重置" → 恢复初始值 50
```

---

## 十一、记忆系统接口对齐（V2 升级）

> **设计来源**：`01_记忆系统全局设计.md` v1.3
>
> **现状**：V2 代码中 agent_loop.py 调用了 `get_personality()`、`get_standards()`、`search()`，但 memory/manager.py 中缺少这些方法。V2 需要补齐。

### 11.1 MemoryManager 新增接口

```python
# src/memory/manager.py（V2 升级）

class MemoryManager:
    """
    记忆管理器 — V2 升级

    新增方法：
    - get_personality(): 获取第1层 HEXACO 人格
    - get_standards(): 获取第3层标准记忆
    - search(): 与 recall() 等价，兼容设计文档接口
    """

    def get_personality(self) -> dict:
        """
        获取第1层人格（HEXACO 六维）

        返回格式：{"H": 50, "E": 50, "X": 50, "A": 50, "C": 50, "O": 50}
        初始值 50（正态分布中位数），由 7 种算法自动调整。
        """
        result = {}
        dim_map = {"H": "honesty", "E": "emotionality", "X": "extraversion",
                   "A": "agreeableness", "C": "conscientiousness", "O": "openness"}
        for key, attr in dim_map.items():
            result[key] = self.personality.get(attr, 50) if isinstance(self.personality, dict) else getattr(self.personality, attr, 50)
        return result

    def get_standards(self, category: str = None, limit: int = 10) -> list:
        """
        获取第3层标准记忆
        category 不写死，由 LLM 根据任务类型动态确定
        limit 不写死，由 LLM 根据上下文窗口大小动态确定
        """
        return asyncio.run(self.storage.search("", layer="standard", limit=limit))

    async def search(self, query: str, layer: str = None, limit: int = 10) -> list:
        """搜索记忆（与 recall 等价，兼容设计文档接口）"""
        return await self.recall(query, layer=layer, limit=limit)
```

---

## 十二、可观测性升级（V2）

### 12.1 Prometheus + Grafana

```python
# src/observability/prometheus_exporter.py

class PrometheusExporter:
    """
    V2 升级：集成 Prometheus + Grafana

    V1：结构化 JSON 日志 + perf_counter → 日志
    V2：Prometheus histogram + counter + 告警规则
    """

    # 关键指标
    LLM_LATENCY = Histogram('llm_call_latency_seconds', 'LLM 调用延迟')
    MEMORY_RETRIEVAL_LATENCY = Histogram('memory_retrieval_latency_seconds', '记忆检索延迟')
    AGENT_LOOP_DURATION = Histogram('agent_loop_duration_seconds', '主循环耗时')
    COMPRESSION_RATIO = Histogram('context_compression_ratio', '上下文压缩比')
    LLM_ERROR_RATE = Counter('llm_errors_total', 'LLM 错误计数')
```

---

## 十三、测试策略（V2 升级）

### 13.1 测试目录结构（清理后）

```
tests/
├── conftest.py                       # 全局 fixture
├── fixtures/
│   ├── personality_valid.md
│   └── personality_invalid.md
├── unit/
│   ├── test_memory_manager.py
│   ├── test_personality_schema.py
│   ├── test_error_classifier.py
│   ├── test_input_filter.py
│   ├── test_state_machine.py
│   ├── test_understanding.py
│   ├── test_context_compressor.py
│   ├── test_execution_supervisor.py  # V2 新增
│   ├── test_result_verifier.py       # V2 新增
│   ├── test_model_router.py          # V2 新增
│   ├── test_prompt_manager.py        # V2 新增
│   ├── test_session_manager.py       # V2 新增
│   ├── test_approval_module.py       # V2 新增
│   ├── test_conflict_checker.py      # V2 新增
│   └── test_personality_algorithms.py # V2 新增
├── integration/
│   ├── test_agent_loop.py
│   ├── test_entry_system.py
│   ├── test_llm_provider.py
│   ├── test_execution_flow.py        # V2 新增
│   └── test_delivery_flow.py         # V2 新增
└── verify_v1.py                      # V1 功能验证（保留）
```

> **清理动作**：将 `tests/debug/` 和 `tests/debug_*.py` 移到 `scripts/debug/` 或删除。

### 13.2 覆盖率目标

| 模块 | V1 覆盖率目标 | V2 覆盖率目标 |
|------|-------------|-------------|
| 记忆系统 | > 95% | > 95% |
| 上下文压缩 | > 90% | ✅ 17 tests |
| 理解层 | > 80% | > 85% |
| 执行层 | — | > 85% |
| 交付层 | — | > 85% |
| LLM 管理 | — | > 80% |
| 会话管理 | — | > 85% |
| 安全审批 | — | > 85% |
| 整体 | > 85% | > 85% |

---

## 十四、开发流程（V2）

### 14.1 V2 开发阶段

```
阶段①：基础升级（1-2 周）
  ├── 建 Git 仓库
  ├── 清理测试目录（debug 脚本移出）
  ├── 上下文压缩引擎 V2（双锚点+10算法评分+幂律裁剪 + CompressResult 9字段）
  ├── 记忆系统接口对齐（get_personality/search/get_standards）
  └── 人格系统完善（7 种算法）

阶段②：核心模块（2-3 周）
  ├── 执行层（BSupervisor + GoalAnchor + ToolRegistry + SnapshotManager + SubAgentManager）
  ├── 交付层（ResultVerifier + ReportGenerator + ConfirmationManager）
  └── 安全审批（SecurityGuard + ApprovalModule + ConflictChecker + CredentialPool）

阶段③：扩展模块（1-2 周）
  ├── LLM 管理（ModelRouter + PromptManager）
  ├── 会话管理（SessionManager + IdentityManager + EventBus）
  └── 状态机完善（触发器 + 进入/退出动作 + 并发消息处理 + 状态持久化）

阶段④：集成测试（1 周）
  ├── 集成测试 + 端到端测试
  ├── 覆盖率达标
  └── Code Review

阶段⑤：发布 + 监控
  ├── Prometheus + Grafana
  ├── 告警规则
  └── 文档更新
```

### 14.2 PR 规范

```
每个 PR 必须包含：
1. 变更说明（改了什么、为什么改）
2. 测试覆盖（新增/修改的测试）
3. 红线自查（安全/架构/代码质量/测试/部署）
4. 性能影响（是否有性能回退）
5. 安全影响（是否有安全风险）

Review 流程：
1. 至少 1 人 Review
2. CI 必须通过（lint + type check + test + coverage）
3. 合并后自动部署到测试环境
```

---

## 十五、文件结构（V2 完整）

```
long_agent/
├── pyproject.toml
├── config.yaml
├── .env
├── data/
│   ├── personality.md
│   ├── memory.db
│   ├── standards/
│   └── backups/
├── logs/
│   └── agent.log
├── snapshots/
├── migrations/
│   └── 001_initial.sql
├── scripts/
│   └── debug/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── entry/
│   │   ├── cli.py
│   │   ├── library.py
│   │   └── signals.py
│   ├── config/
│   │   └── settings.py
│   ├── loop/
│   │   ├── agent_loop.py
│   │   ├── state.py              # V2 升级：触发器 + 进入/退出动作
│   │   ├── message_queue.py      # V2 新增：并发消息处理
│   │   └── state_persistence.py  # V2 新增：状态持久化
│   ├── memory/
│   │   ├── manager.py            # V2 升级：get_personality/search/get_standards
│   │   ├── storage/
│   │   │   ├── base.py
│   │   │   └── sqlite_storage.py
│   │   └── personality/          # V2 升级：7 种算法
│   │       ├── pid_controller.py
│   │       ├── kalman_filter.py
│   │       ├── bayesian_update.py
│   │       ├── reinforcement_learning.py
│   │       ├── multi_armed_bandit.py
│   │       ├── fuzzy_controller.py
│   │       └── entropy_controller.py
│   ├── context/
│   │   ├── compressor.py         # V2：CompressResult 10字段 + 双锚点 + 10算法评分 + 幂律裁剪
│   │   └── algorithms/
│   │       ├── confidence_threshold.py
│   │       ├── clarification_budget.py
│   │       ├── clarification_strategy.py
│   │       └── logistic_growth.py
│   ├── understanding/
│   │   └── engine.py
│   ├── execution/                # V2 新增：执行层
│   │   ├── __init__.py
│   │   ├── b_supervisor.py
│   │   ├── goal_anchor.py
│   │   ├── tool_registry.py
│   │   ├── snapshot_manager.py
│   │   ├── subagent_manager.py
│   │   └── process_standard.py
│   ├── delivery/                 # V2 新增：交付层
│   │   ├── __init__.py
│   │   ├── result_verifier.py
│   │   └── report_generator.py   # 含 ConfirmationManager
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── provider.py
│   │   ├── model_router.py       # V2 新增
│   │   └── prompt_manager.py     # V2 新增
│   ├── session/                  # V2 新增：会话管理
│   │   ├── __init__.py
│   │   ├── session_manager.py
│   │   ├── identity_manager.py
│   │   └── event_bus.py
│   ├── security/
│   │   ├── filter.py
│   │   ├── guard.py              # V2 新增：SecurityGuard
│   │   ├── approval_module.py    # V2 新增
│   │   ├── conflict_checker.py   # V2 新增
│   │   └── credential_pool.py    # V2 新增
│   ├── errors/
│   │   ├── __init__.py
│   │   ├── types.py
│   │   └── classifier.py
│   ├── background/
│   │   └── manager.py
│   └── observability/
│       ├── __init__.py
│       ├── metrics.py
│       ├── health.py
│       └── prometheus_exporter.py  # V2 新增
└── tests/
    ├── conftest.py
    ├── fixtures/
    ├── unit/
    ├── integration/
    └── verify_v1.py
```

---

## 十六、变更记录

| 日期 | 版本 | 变更 | 操作人 |
|------|------|------|--------|
| 2026-05-02 | v2.0 | V2 初始版本：定义完整架构 + 10 算法压缩引擎 + 执行层 + 交付层 + LLM 管理 + 会话管理 + 人格完善 + 可观测性升级 + 开发流程 | — |
| 2026-05-03 | v2.1 | 融合 hermse v1.3：新增常驻后台压缩进程 + 双锚点保边 + 读写锁并行 + 反馈闭环 | 十一 |
| 2026-05-03 | v2.2 | **第四次修订**：基于 mylong/记忆模块设计/long/ 01~09 深度融合版全面更新。主要变更：①上下文压缩引擎改为双锚点+10算法评分+幂律裁剪）+ CompressResult；②执行层补充 SubAgentManager + ProcessStandard；③交付层补充 ConfirmationManager；④安全审批模块拆分为 SecurityGuard + ApprovalModule + ConflictChecker + CredentialPool；⑤LLM 管理改为极简（回退链 + 冷却 + UI接口，去掉任务分级和成本优化）；⑥会话管理补充 IdentityManager + EventBus；⑦状态机补充并发消息处理 + 状态持久化；⑧人格系统 7 种算法全部列出且参数不写死；⑨记忆系统接口对齐（get_personality/search/get_standards）；⑩所有模块参数标注不写死原则 | 十一 |
| 2026-05-03 | v2.3 | **开发方案追加**：新增第十七章（开发执行方案），定义三阶段开发计划、决策点、用户融入机制 | 十一 |

---

## 十七、开发执行方案

> **本章目的**：定义V2从设计到交付的具体开发路径，确保文档和代码一致，用户可随时融入新想法。

### 17.1 当前状态诊断

| 维度 | 状态 |
|------|------|
| V1代码 | ~6900行，4335行测试，核心骨架已跑通 |
| V2设计 | DESIGN-V2.md 1862行 + 9篇设计文档（~400KB） |
| V2代码 | 执行层（BSupervisor/GoalAnchor/SnapshotManager/ToolRegistry）和compressor.py已写，但**孤立存在，未被AgentLoop调用** |
| 核心矛盾 | 文档和代码断层：设计归设计，代码归代码 |

### 17.2 开发阶段划分

#### 阶段一：打通主干（优先级最高）

**目标**：让V2新增模块真正接入AgentLoop主循环，形成可运行的完整链路。

| 序号 | 任务 | 说明 | 预估代码量 |
|------|------|------|-----------|
| 1 | AgentLoop接入执行层 | `_step_execute()` 中调用BSupervisor替代当前简单分支 | ~200行修改 |
| 2 | AgentLoop接入交付层 | `_step_observe()` 中调用ResultVerifier + ReportGenerator | ~150行修改 |
| 3 | ContextCompressor注入感知阶段 | ✅ 已完成（T2） | ~100行修改 |
| 4 | MemoryManager补齐V2接口 | `get_personality()` / `get_standards()` / `search()` | ~80行新增 |
| 5 | 状态机完善 | 进入/退出动作从`...`占位变成实际逻辑 | ~150行新增 |

**完成标准**：AgentLoop一次完整7步循环能跑通所有V2新增模块。

#### 阶段二：补齐缺失模块

**目标**：V2设计中有文档但没代码的模块，按优先级逐个实现。

| 序号 | 模块 | 设计文档 | 优先级 |
|------|------|---------|--------|
| 1 | ResultVerifier + ReportGenerator + ConfirmationManager（交付层） | 04_交付层设计.md | 🔴高 |
| 2 | SessionManager + IdentityManager + EventBus（会话管理） | 08_会话管理设计.md | 🔴高 |
| 3 | ModelRouter + PromptManager（LLM管理） | 07_LLM管理设计.md | 🟡中 |
| 4 | SecurityGuard + ApprovalModule + ConflictChecker（安全审批） | 05_安全与治理设计.md | 🟡中 |
| 5 | 人格系统7种算法 | 01_记忆系统全局设计.md | 🟡中 |
| 6 | 可观测性升级（Prometheus + Grafana） | DESIGN-V2 §十二 | 🟢低 |

**开发顺序规则**：先上游后下游，先高优先级后低优先级。每个模块开发前先读对应设计文档，开发后更新接口契约。

#### 阶段三：测试覆盖 + 集成验证

1. 每个模块写完即写单元测试（TDD原则）
2. 集成测试：端到端跑通3个典型场景（简单对话、工具调用、记忆读写）
3. 压力测试：长对话（100+轮）下上下文压缩是否正常 ✅
4. 代码审查：对照设计文档逐项检查实现完整性

### 17.3 决策点记录

| 编号 | 问题 | 决策 |
|------|------|------|
| D-01 | 文档和代码同步顺序 | **先改代码，再同步文档**，避免文档改了代码没改 |
| D-02 | SubAgentManager是否纳入阶段一 | **阶段二再做**，先把单Agent主干跑通 |
| D-03 | 人格7种算法分批策略 | **分批**，初期先做PID+卡尔曼+模糊控制（3种），后期补全 |
| D-04 | V1 debug脚本处理 | **清理** tests/debug/ 下30+个临时文件，保留正式单元测试 |

### 17.4 用户融入机制

开发过程中用户可随时提出新想法，处理流程：

1. **每个阶段完成后汇报**，确认后进入下一阶段
2. **每个模块开发前先输出简要设计**（接口定义+关键逻辑），用户确认后再编码
3. **新想法影响当前模块**：先评估影响范围（改几个文件、影响几个测试），输出影响报告，用户确认后改
4. **新想法影响整体架构**：先停，更新DESIGN-V2和相关设计文档，再继续
5. **沟通记录**：所有决策写入本章17.3决策点表

---

## 附：Skill 与 MCP 系统设计

### Skill 系统
| 模块 | 职责 | 状态 |
|------|------|------|
| src/skill/manager.py | Skill 加载/注册/执行 | ⬜ 待开发 |
| skins/builtins/ | 内置 Skill | ⬜ 待开发 |

### MCP 服务器
| 模块 | 职责 | 状态 |
|------|------|------|
| src/mcp/server.py | 轻量 JSON-RPC 服务 | ⬜ 待开发 |

详细设计见 `设计文档/10_Skill与MCP设计.md`
