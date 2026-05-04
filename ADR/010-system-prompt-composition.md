# ADR-010：System Prompt 组成

## 状态
Accepted

## 日期
2026-05-03

## 背景
V1 的 System Prompt 是静态拼接，缺乏结构化组成：
- 人格、核心、标准记忆混在一起
- 无预算分配，所有记忆都塞进 Prompt
- 动态内容（当前上下文）与静态内容（人格）无区分

## 决策
采用四层结构的 System Prompt 组成：

### System Prompt 结构

```
System Prompt
├── 1. 人格层（固定，不受预算限制）
│   └── personality.md 中的 H/E/X/A/C/O 维度
│
├── 2. 核心层（按项目，受预算限制）
│   └── 当前项目的核心记忆（layer="core"）
│   └── 预算：Token 预算的 30%（相关加载）
│
├── 3. 标准层（按任务，受预算限制）
│   └── 与当前任务相关的标准记忆（layer="standard"）
│   └── 预算：Token 预算的 20%（高价值加载）
│
└── 4. 动态层（预算分配）
    ├── 热区 40%：最近访问的记忆
    ├── 相关 30%：与当前输入互信息最高的记忆
    ├── 高价值 20%：香农熵最高的记忆
    └── 锚点 10%：不可淘汰的记忆
```

### 各层职责

| 层 | 内容 | 预算 | 更新频率 |
|----|------|------|---------|
| 人格层 | H/E/X/A/O/C 六维度 | 固定 | 用户反馈调整 |
| 核心层 | 项目核心记忆 | 30% | 项目进展更新 |
| 标准层 | 任务相关标准 | 20% | 任务完成更新 |
| 动态层 | 按预算动态加载 | 40%+10% | 每次请求重新计算 |

### 记忆加载调用链

```
AgentLoop._step_perceive()
    → MemoryManager.load_memories_for_context(current_input)
        → MemoryLoader.load_memories(all_memories, current_input, budget)
            → 热区加载（40%）
            → 相关加载（30%，互信息 I(X;Y)）
            → 高价值加载（20%，香农熵 H(X)）
            → 锚点加载（10%）
    → MemoryManager.build_system_prompt_memories()
        → 人格层（固定）
        → 核心层 + 标准层（按预算）
        → 动态层（预算分配）
```

### 淘汰触发
每次写入新记忆后，调用 `MemoryManager.check_and_evict()`：
1. 计算 eviction_score = (N/K)^α
2. 若 eviction_score > 0.85，触发淘汰
3. 使用 MemoryEvictor 淘汰低价值记忆
4. 锚点记忆不受影响

## 后果
- ✅ System Prompt 结构清晰，各层职责明确
- ✅ 预算分配合理，高价值记忆优先加载
- ✅ 人格层固定，保证 Agent 行为一致性
- ✅ 动态层按请求重新计算，保证上下文相关性
- ⚠️ 需要在 AgentLoop._step_perceive() 中接入 MemoryManager

## 参考
- ADR-008：记忆系统联动架构
- ADR-009：动态记忆加载算法
- "开始的上下文.txt" §System Prompt 组成
