# Loop 模块 — 接口契约

> **版本**：v2.1 | **日期**：2026-05-03

---

## AgentLoop 类

### 构造函数

```python
class AgentLoop:
    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        memory_manager: Optional[MemoryManager] = None,
        state_machine: Optional[StateMachine] = None,
        b_supervisor: Optional[BSupervisor] = None,          # V2
        compressor: Optional[ContextCompressor] = None,      # V2
        result_verifier: Optional[ResultVerifier] = None,     # V2
        report_generator: Optional[ReportGenerator] = None,  # V2
    )
```

### 核心方法

```python
async def run(self, user_input: str, conversation_id: str = "") -> str
"""
执行完整的 7 步循环，返回最终回复文本。

7 步：
  ① PERCEIVING   → _step_perceive()
  ② UNDERSTANDING → _step_understand()
  ③ PLANNING     → _step_plan()
  ④ EXECUTING    → _step_execute()
  ⑤ OBSERVING    → _step_observe()
  ⑥ REFLECTING   → _step_reflect()
  ⑦ REPLYING     → _step_reply()
"""
```

---

## LoopContext 数据类

```python
@dataclass
class LoopContext:
    # 输入
    user_input: str = ""
    conversation_id: str = ""

    # 感知阶段产出
    filtered_input: str = ""
    memory_context: dict = field(default_factory=dict)
    compressed_messages: list = field(default_factory=list)

    # 理解阶段产出
    intent: object = None
    clarification_question: str = ""
    needs_clarification: bool = False

    # 规划阶段产出
    operation_type: str = ""    # memory_write / memory_read / tool_call / llm_chat
    requires_approval: bool = False
    approved: bool = False

    # 执行阶段产出
    llm_result: Optional[LLMResult] = None
    tool_result: Optional[OperationResult] = None
    execution_result: str = ""
    retry_count: int = 0

    # 观察阶段产出
    is_off_track: bool = False
    off_track_reason: str = ""

    # 反思阶段产出
    memory_updated: bool = False
    background_tasks_triggered: bool = False

    # 回复阶段产出
    response: str = ""

    # 元数据
    loop_id: str = ""
    started_at: str = ""
    error: str = ""
```

---

## 状态机（StateMachine）

```python
class StateMachine:
    def transition_to(self, new_state: AgentState) -> bool
    """状态转换，非法转换返回 False"""

    def can_transition(self, from_state: AgentState, to_state: AgentState) -> bool
    """检查转换是否合法"""
```

### 11 个状态

```
IDLE → PERCEIVING → UNDERSTANDING → PLANNING → EXECUTING → OBSERVING → REFLECTING → REPLYING → IDLE
                                              ↘ WAITING → EXECUTING
                                                                    ↘ FAILED → IDLE
```

---

## 模块级函数

```python
def _build_plan_from_intent(intent, operation_type: str) -> Plan
"""
从 intent 构建 plan 对象。
Plan 包含：deliverable / acceptance_criteria / max_steps
"""
```
