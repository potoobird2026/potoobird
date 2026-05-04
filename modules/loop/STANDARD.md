# modules/loop/STANDARD.md — Loop 模块标准

> **定位**：Loop 模块的"主心骨"。开发 Loop 相关代码时必须遵守。
> **加载规则**：开发 Loop 模块时加载，替换式（不叠加）。

---

## 模块职责

**一句话**：驱动 Agent 的 7 步循环，管理状态转换，调度各子模块。

**边界**：
- ✅ 负责：主循环调度、状态机驱动、步骤方法编排
- ❌ 不负责：具体业务逻辑（由子模块处理）、LLM 调用（由 llm 模块处理）、记忆读写（由 memory 模块处理）

---

## 核心接口

### AgentLoop 类

```python
class AgentLoop:
    """Agent 主循环 — 7 步循环 + 状态机驱动"""
    
    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        memory_manager: Optional[MemoryManager] = None,
        state_machine: Optional[StateMachine] = None,
        b_supervisor: Optional[BSupervisor] = None,      # V2
        result_verifier: Optional[ResultVerifier] = None,  # V2
        report_generator: Optional[ReportGenerator] = None, # V2
        context_compressor: Optional[ContextCompressor] = None, # V2
    )
    
    async def run(self, user_input: str, conversation_id: str = None) -> str:
        """执行完整的 7 步循环，返回回复文本"""
    
    async def stop(self):
        """优雅停止"""
```

### 步骤方法（V2 设计）

**步骤方法只管业务逻辑，不做状态转换，不检查 running 状态。**

```python
async def _step_perceive(self, ctx: LoopContext) -> None:
    """① 感知：读取输入 + 加载上下文 + 上下文压缩"""

async def _step_understand(self, ctx: LoopContext) -> None:
    """② 理解：意图解析 + 置信度评估 + 追问决策"""

async def _step_plan(self, ctx: LoopContext) -> None:
    """③ 规划：确定操作类型 + 审批检查"""

async def _step_execute(self, ctx: LoopContext) -> None:
    """④ 执行：调用 LLM / 工具 / 写入记忆（BSupervisor 保护）"""

async def _step_observe(self, ctx: LoopContext) -> None:
    """⑤ 观察：检查结果（ResultVerifier 验证）"""

async def _step_reflect(self, ctx: LoopContext) -> None:
    """⑥ 反思：更新记忆 + 触发后台任务"""

async def _step_reply(self, ctx: LoopContext) -> None:
    """⑦ 回复：格式化输出（ReportGenerator 生成报告）"""
```

---

## 设计约束

1. **步骤方法职责单一**：只做业务逻辑，不做状态转换，不检查 running
2. **状态转换由 run() 统一管理**：在调用步骤前后做 transition_to()
3. **所有子模块通过构造函数注入**：不硬编码依赖
4. **子模块为 Optional**：缺失时使用降级逻辑（V1 兼容）
5. **LoopContext 传递所有上下文**：步骤方法之间通过 ctx 共享数据
6. **错误恢复**：每个步骤的异常在 run() 中捕获，记录日志，降级处理

---

## LoopContext 数据类

```python
@dataclass
class LoopContext:
    user_input: str = ""
    conversation_id: str = ""
    loop_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # 各步骤产出
    filtered_input: str = ""
    intent: Optional[Intent] = None
    llm_result: Optional[LLMResult] = None
    execution_result: Optional[str] = None
    verify_report: Optional[VerificationReport] = None
    response: str = ""
    
    # 控制流
    needs_clarification: bool = False
    clarification_question: str = ""
    requires_approval: bool = False
    operation_type: str = ""
    
    # 上下文
    memory_context: dict = field(default_factory=dict)
    compressed_messages: list = field(default_factory=list)
```

---

## 测试要求

- 步骤方法可独立测试（不依赖状态机前置状态）
- 每个步骤至少 5 个测试用例
- run() 集成测试覆盖正常流程 + 异常流程
- 覆盖率 ≥ 90%

---

## 依赖关系

```
loop 模块依赖：
├── state（状态机）— 必须
├── memory（MemoryManager）— Optional
├── llm（LLMClient）— Optional
├── execution（BSupervisor）— V2, Optional
├── delivery（ResultVerifier, ReportGenerator）— V2, Optional
└── context（ContextCompressor）— V2, Optional

loop 模块被以下模块调用：
├── main.py（CLI 入口）
└── session（SessionManager）— V2
```

---

> **版本**：v2.1 | **最后更新**：2026-05-03
