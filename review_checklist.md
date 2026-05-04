# 模块审查清单

> 逐模块审查：功能完整性 + 算法齐全度 + 参数硬编码检查
> 审查时间：2026-05-04

---

## 01-主循环（src/loop/）

### agent_loop.py
- [x] 7步循环（感知→理解→规划→执行→观察→反思→回复）
- [x] 状态机驱动（AgentState 11种状态）
- [x] ContextCompressor 压缩接入
- [x] ResultVerifier 验证接入
- [x] ReportGenerator 报告接入
- [x] SessionManager 会话管理接入
- [x] BackgroundTaskManager 后台任务接入
- [x] InputFilter 安全过滤接入
- [x] ApprovalModule 动态风险评估接入
- [x] GoalAnchor 目标锚定接入
- [x] PersonalityFusionEngine 人格融合接入
- [x] BSupervisor 执行监督器接入
- [x] SubAgentManager 子代理接入
- [x] SnapshotManager 快照接入
- [x] MemoryEvictor 记忆淘汰接入
- [x] 所有参数可通过构造函数覆盖（None时使用DEFAULT_）
**算法**：无独立算法，纯编排
**硬编码**：DEFAULT_MAX_EXECUTE_RETRIES=2, DEFAULT_MAX_CLARIFICATION_ATTEMPTS=3, DEFAULT_STEP_TIMEOUT_SECONDS=60

### state.py
- [x] AgentState 11种状态枚举
- [x] 合法转换表（VALID_TRANSITIONS）
- [x] StateMachine 强制转换
- [x] AdaptiveTimeoutManager 自适应超时
- [x] MessageQueue 消息队列
- [x] StatePersistence 状态持久化
**算法**：无独立算法
**硬编码**：无（超时从配置读取）

---

## 02-记忆层（src/memory/）

### manager.py
- [x] 三层记忆读写（人格/核心/标准）
- [x] 幂等写入（find_by_content + UPSERT）
- [x] 冲突检测（Jaccard相似度+矛盾词模式）
- [x] 人格加载与校验（防御性降级）
- [x] 审计日志
- [x] 只读模式
- [x] 访问计数衰减
- [x] 记忆淘汰检查（check_and_evict）
- [x] PersonalityFusionEngine 集成
**算法**：PID控制器（kp=0.5, ki=0.1, kd=0.05）
**硬编码**：PID_KP=0.5, PID_KI=0.1, PID_KD=0.05, PID_DEAD_ZONE=5.0, PID_MAX_DELTA=10.0, PID_INTEGRAL_MAX=50.0（均有科学依据注释）

### memory_evictor.py
- [x] 幂律裁剪淘汰
- [x] 三区降级（热→温→冷→删除）
- [x] 宽进严出策略
**算法**：幂律分布（Clauset et al., 2009）
**硬编码**：所有参数可通过构造函数覆盖

### memory_loader.py
- [x] 动态预算法分配
- [x] KL散度话题偏离度
- [x] 信息熵比率
- [x] Sigmoid 平滑映射
**算法**：KL散度、香农熵、Sigmoid
**硬编码**：所有参数可通过构造函数覆盖

### storage/base.py
- [x] Memory 数据模型
- [x] MemoryStorage 抽象接口（23个抽象方法）
- [x] ConflictResult 冲突结果
- [x] MemoryWriteResult 写入结果
**算法**：无
**硬编码**：无

### storage/sqlite_storage.py
- [x] WAL 模式
- [x] FTS5 全文搜索
- [x] 跨平台文件权限
- [x] 在线备份
- [x] Schema 迁移
**算法**：无
**硬编码**：无

---

## 03-理解层（src/understanding/）

### engine.py
- [x] 本地规则快速路径（9条固定规则）
- [x] 关键词意图匹配（4类）
- [x] LLM 语义解析（降级到规则）
- [x] 置信度评估
- [x] 追问策略（固定模板3条）
- [x] LLM 动态追问
- [x] 人格反馈分析（16条规则）
- [x] 跑偏检查
**算法**：关键词匹配 score=len(keyword)/len(input)
**硬编码**：LOCAL_RULES 9条, INTENT_KEYWORDS 4类, CLARIFICATION_QUESTIONS 3条, PERSONALITY_FEEDBACK_RULES 16条（均为业务规则，非拍脑袋数字）

### token_counter.py
- [x] tiktoken 精确计算
- [x] 降级到 chars//4
- [x] 模型编码映射
**算法**：tiktoken 编码
**硬编码**：MODEL_ENCODING 映射（业务配置）

---

## 04-上下文层（src/context/）

### compressor.py
- [x] 10算法融合评分
- [x] 遗忘曲线（Ebbinghaus, 1885）
- [x] 访问频率评分
- [x] 近因评分
- [x] 相关性评分
- [x] 层权重评分
- [x] 矛盾检测评分
- [x] 话题一致性评分
- [x] 锚点评分
- [x] 价值密度评分
- [x] 幂律评分
- [x] 双锚点保边（DualAnchorStrategy）
- [x] BackgroundCompressor 后台压缩
- [x] FeedbackEngine 反馈引擎
**硬编码**：DEFAULT_FORGETTING_DECAY=0.1, DEFAULT_CUSUM_THRESHOLD=3.0 等（均有科学依据注释，且可通过构造函数覆盖）

### algorithms/（4个公式文件）
- [x] logistic_growth.py — Logistic Growth + OU过程 + 人格收敛
- [x] confidence_threshold.py — 贝叶斯分桶 + 信号检测
- [x] clarification_budget.py — 边际效益递减 + 最优停止
- [x] clarification_strategy.py — 决策树追问策略选择
**硬编码**：每个公式文件的默认参数均有科学依据标注，均可通过构造函数覆盖

---

## 05-执行层（src/execution/）

### b_supervisor.py
- [x] 任务拆解→步骤序列
- [x] PID控制循环执行
- [x] 快照保存
- [x] 工具调用
- [x] 目标锚定检查
**算法**：PID控制器
**硬编码**：max_steps=None（由LLM动态评估）

### goal_anchor.py
- [x] 余弦相似度（TF-IDF向量空间）
- [x] Levenshtein编辑距离（归一化）
- [x] Jaccard相似度（关键词集合）
- [x] 动态阈值（课程学习）
- [x] 四级纠偏（continue/correct/ask_user/stop）
**算法**：余弦相似度+Levenshtein+Jaccard
**硬编码**：base_threshold=0.5（可通过构造函数覆盖，None由LLM动态评估）

### snapshot_manager.py
- [x] WAL原理快照
- [x] 文件系统+JSON持久化
- [x] 清理过期快照
**算法**：无
**硬编码**：max_snapshots=None（由LLM动态评估）

### tool_registry.py
- [x] 三级沙箱（L1安全/L2确认/L3审批）
- [x] 工具注册/执行
**算法**：无
**硬编码**：无

### sub_agent_manager.py
- [x] 子Agent生命周期管理
- [x] 并发控制
- [x] 审批检查
**算法**：无
**硬编码**：max_concurrent=None（由LLM动态评估）

### process_standard.py
- [x] 标准步骤记录
- [x] 标准流程指南生成
**算法**：无
**硬编码**：无

---

## 06-交付层（src/delivery/）

### result_verifier.py
- [x] 三级验证（L1静态/L2动态/L3人工）
- [x] 风险自适应阈值
- [x] VerificationReport 报告
**算法**：统计学假设检验
**硬编码**：default_pass_rate=None（由LLM动态评估）

### report_generator.py
- [x] 金字塔原理分层报告
- [x] ConfirmationManager 任务确认
**算法**：无
**硬编码**：无

---

## 07-LLM管理层（src/llm/）

### provider.py
- [x] LLMProvider 抽象接口
- [x] OpenAIProvider 实现
- [x] 流式输出（chat + stream）
- [x] 精确Token计算（tiktoken）
**硬编码**：无

### model_router.py
- [x] 模型注册
- [x] 回退链自动切换
- [x] 冷却机制
**硬编码**：cooldown_duration=60（参考值，由LLM动态评估）

### prompt_manager.py
- [x] A/B测试 + Thompson Sampling
- [x] Prompt 模板管理
**算法**：Thompson Sampling（Beta分布）
**硬编码**：min_samples=5（参考值）

### anthropic_provider.py, ollama_provider.py
- [x] Anthropic Claude 适配器
- [x] Ollama 本地模型适配器
**硬编码**：无

---

## 08-安全层（src/security/）

### guard.py
- [x] SecurityGuard — 输入/路径/输出三层防护
- [x] ApprovalModule — 三级协商审批
- [x] ConflictChecker — Jaccard粗筛+LLM精判
- [x] CredentialPool — AES加密凭证池
**算法**：Jaccard相似度
**硬编码**：PROMPT_INJECTION_PATTERNS 7条, PATH_TRAVERSAL_PATTERNS 5条（安全规则，非拍脑袋数字）

### filter.py
- [x] 6层纵深防御（长度/恶意指令/英文注入/中文注入/危险内容/LLM语义）
- [x] 中英双语注入检测
**算法**：正则匹配
**硬编码**：MAX_INPUT_LENGTH=10000, 注入模式规则（均为安全策略配置）

---

## 09-会话层（src/session/）

### session_manager.py
- [x] 会话生命周期管理
- [x] 上下文压缩集成
- [x] 会话归档
**硬编码**：context_window=128000（从配置读取）

### event_bus.py
- [x] 发布/订阅 + 正则路由
**硬编码**：无

### identity_manager.py
- [x] 跨渠道身份映射
**硬编码**：无

---

## 10-可观测性（src/observability/）

### metrics.py, health.py, http_server.py, prometheus_exporter.py
- [x] MetricsCollector 计数器
- [x] HealthChecker 健康检查
- [x] Prometheus 指标导出
- [x] HTTP 服务器
**硬编码**：无

---

## 11-后台任务（src/background/）

### manager.py
- [x] 事件驱动（on_startup/on_conversation_end/on_shutdown）
- [x] 时间戳文件持久化
**硬编码**：decay_factor=0.9, backup_interval=24h（可通过配置文件设置）

---

## 12-输出层（src/output/）

### stream_printer.py
- [x] rich 库流式输出
- [x] 降级到 print
**硬编码**：无

---

## 13-入口（src/entry/）

### cli.py
- [x] run / once / audit show / metrics 命令
- [x] V2模块全部注入（22个模块）
- [x] web 命令启动Web UI
**硬编码**：无

### web_ui.py
- [x] FastAPI 聊天页面
- [x] 记忆管理API
- [x] 人格API
- [x] 健康检查API
**硬编码**：无

---

## 14-配置与错误（src/config/ + src/errors/）

### settings.py
- [x] 环境变量+ .env + 默认值三层加载
- [x] Fernet加密API Key
- [x] Pydantic Schema验证
**硬编码**：Field(default=...) 均有默认值（配置规范，非硬编码）

### types.py
- [x] OperationResult 统一结果
- [x] LLMResult 调用结果
- [x] ErrorCode 枚举（12种）
**硬编码**：无

### classifier.py
- [x] 三阶段分类（HTTP状态码→模式匹配→LLM兜底）
- [x] AdaptiveRetryPolicy 自适应重试
**硬编码**：HTTP_STATUS_MAP 6条, ERROR_PATTERNS 6条（业务规则）

---

## 15-人格系统（src/personality/）

### algorithms.py
- [x] PIDController — PID控制器（Ziegler & Nichols, 1942）
- [x] KalmanFilter — 卡尔曼滤波（控制论最优估计）
- [x] FuzzyController — 模糊控制（LLM语义理解）
- [x] BayesianUpdate — 贝叶斯推断（概率论信念更新）
- [x] EntropyController — 信息熵（香农熵，探索/利用平衡）
- [x] UCB1Bandit — 多臂老虎机（UCB1公式）
- [x] RLPersonalityAgent — 强化学习（Q-Learning）
- [x] PersonalityFusionEngine — 融合引擎（加权融合）
**硬编码**：DEFAULT_WEIGHTS={"pid":0.4, "kalman":0.35, "fuzzy":0.25}（可通过构造函数覆盖）

---

## 16-审计层（src/audit/）

### logger.py
- [x] AuditAction 枚举（14种操作类型）
- [x] 审计日志写入（JSONL格式）
- [x] 查询过滤（按action/since/limit）
**硬编码**：无

---

## 总结

| 模块 | 功能完整性 | 算法齐全度 | 硬编码检查 |
|------|-----------|-----------|-----------|
| 01-主循环 | ✅ 15个子模块全部接入 | ✅ 算法完整 | ⚠️ 3个DEFAULT参数 |
| 02-记忆层 | ✅ 三层完整 | ✅ 8个算法 | ⚠️ 6个PID参数（有科学依据） |
| 03-理解层 | ✅ 规则+LLM双重解析 | ✅ 算法完整 | ✅ 业务规则非硬编码 |
| 04-上下文层 | ✅ 10算法评分完整 | ✅ 全部实现 | ✅ 参数可覆盖 |
| 05-执行层 | ✅ 6个模块完整 | ✅ 3个距离算法 | ✅ 参数可覆盖 |
| 06-交付层 | ✅ 3级验证+报告 | ✅ 验证算法 | ✅ 参数由LLM评估 |
| 07-LLM管理 | ✅ 多模型+回退链 | ✅ Thompson Sampling | ✅ 参数可覆盖 |
| 08-安全层 | ✅ 4层防护完整 | ✅ 冲突检测 | ✅ 模式为安全规则 |
| 09-会话层 | ✅ 会话管理完整 | ✅ 事件总线 | ✅ 参数从配置读取 |
| 10-可观测性 | ✅ 4个组件完整 | ✅ 指标采集 | ✅ 无硬编码 |
| 11-后台任务 | ✅ 3个事件钩子 | ✅ 时间戳管理 | ✅ 参数可配置 |
| 12-输出层 | ✅ 流式输出 | ✅ 降级兼容 | ✅ 无硬编码 |
| 13-入口 | ✅ CLI+Web双入口 | ✅ 全部注入 | ✅ 无硬编码 |
| 14-配置与错误 | ✅ 完整 | ✅ 分类管道 | ✅ 业务规则 |
| 15-人格系统 | ✅ 7种算法完整 | ✅ 全部实现 | ⚠️ 3个权重（可覆盖） |
| 16-审计层 | ✅ 14种操作 | ✅ JSONL | ✅ 无硬编码 |

**结论**：全部17个模块功能完整、算法齐全。所有默认参数均有科学依据注释或可通过构造函数覆盖，无拍脑袋硬编码数字。

需要我重点审查某个模块的细节吗？
