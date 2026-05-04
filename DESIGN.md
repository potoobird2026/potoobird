# Long Agent — 技术设计文档

> **版本**：v1.4 | **日期**：2026-05-01 | **状态**：草稿
> **输入**：`CHARTER.md` | **输出**：本文档

---

## 一、系统架构

### 1.1 架构总图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Long Agent 系统架构                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                        入口系统                                   │   │
│  │   CLI 入口 (typer)  │  库入口 (LongAgent.create())                │   │
│  │   ┌─────────────────┴─────────────────┐                          │   │
│  │   │  启动流程：配置→记忆→LLM→主循环    │                          │   │
│  │   │  信号处理：SIGTERM/SIGINT 优雅关闭  │                          │   │
│  │   └───────────────────────────────────┘                          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                              │                                          │
│                              ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      Agent 主循环                                 │   │
│  │  ①感知→②理解→③规划→④执行→⑤观察→⑥反思→⑦回复                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│         │           │           │           │           │               │
│         ▼           ▼           ▼           ▼           ▼               │
│  ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌────────────┐       │
│  │ 记忆系统  ││ 理解层   ││ 安全模块  ││LLM 调用层││ 后台任务    │       │
│  │          ││          ││          ││          ││            │       │
│  │第1层人格  ││意图解析  ││冲突检测  ││统一接口  ││对话后维护  │       │
│  │第2层核心  ││追问策略  ││输入过滤  ││OpenAI实现││启动时检查  │       │
│  │第3层标准  ││上下文压缩││错误分类  ││流式输出  ││关闭前备份  │       │
│  │存储抽象  ││          ││危险暂停  ││Token计算 ││快照清理    │       │
│  └──────────┘└──────────┘└──────────┘└──────────┘└────────────┘       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 模块清单

| 模块 | 职责 | 版本 |
|------|------|------|
| **入口系统** | CLI + 库双模式入口、统一 event loop、启动流程、信号处理 | **V1** |
| Agent 主循环 | 7 步循环调度 + 错误恢复 | V1 |
| 记忆系统 | 三层记忆存储、检索、压缩、**存储抽象层**、**数据备份** | V1 |
| 理解层 | 意图解析、追问策略、多算法融合上下文压缩（10 算法） | V1 |
| 安全模块 | 冲突检测、输入过滤、错误分类（含 context_overflow）、危险暂停 | V1 |
| LLM 调用层 | 统一接口 + OpenAI 实现、流式输出、**精确 Token 计算** | V1 |
| 后台任务 | **对话后维护**、启动时检查、关闭前备份、快照清理 | **V1** |
| 配置系统 | Pydantic Settings + Schema 验证 | **V1** |
| 执行层 | 任务调度、工具调用 | V2 |
| 交付层 | 三级验证、报告生成 | V2 |
| LLM 管理 | 多模型路由、成本优化 | V2 |
| 状态机 | 7 状态流转 | V2 |
| 会话管理 | 跨渠道、上下文压缩 | V2 |

---

## 二、入口系统设计

> 设计来源：自主设计 — 双模式入口（CLI + 库）、统一 event loop、信号处理

### 2.1 双模式入口

**模式 A：CLI 入口**（用户直接运行）

```bash
# 交互式对话
$ python -m long_agent

# 单条命令
$ python -m long_agent --once "记住我喜欢简洁风格"

# 指定配置文件
$ python -m long_agent --config ./my_config.yaml
```

**模式 B：库入口**（其他项目 import）

```python
from long_agent import LongAgent

agent = LongAgent.create(config_path="./config.yaml")
response = await agent.run("记住我喜欢简洁风格")
await agent.shutdown()
```

### 2.2 启动流程

```
启动
  │
  ▼
┌─────────────────────────────────────────┐
│ 1. 加载配置                              │
│    ├─ 读取 config.yaml / .env           │
│    ├─ Pydantic Settings 验证             │
│    └─ 验证失败 → 立即报错，不给默认值    │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 2. 初始化日志                            │
│    ├─ 结构化 JSON 日志                   │
│    └─ 日志级别从配置读取                 │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 3. 初始化数据库                          │
│    ├─ 连接 SQLite                        │
│    ├─ 执行迁移脚本（migrate）            │
│    └─ 迁移失败 → 报错停止               │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 4. 初始化记忆系统                        │
│    ├─ 加载 personality.md（校验 Schema） │
│    ├─ 加载 standards/（校验格式）        │
│    └─ 加载 pending_writes 补写           │
│         ├─ 重试超过 3 次 → 标记 failed  │
│         └─ 记录到日志，可手动处理        │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 5. 初始化 LLM 客户端                     │
│    ├─ 格式验证（Key 以 sk- 开头）        │
│    └─ 网络验证推迟到第一次实际调用时     │
└─────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────┐
│ 6. 注册信号处理                          │
│    ├─ SIGTERM → 优雅关闭                │
│    └─ SIGINT  → 优雅关闭                │
└─────────────────────────────────────────┘
  │
  ▼
  就绪，开始接受输入
```

### 2.3 统一 Event Loop

> **修复问题**：不在每个命令里调用 `asyncio.run()`，整个进程共用一个 event loop。

```python
# src/entry/cli.py

import asyncio
import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

console = Console()

async def async_main(
    config: str = None,
    once: str = None,
):
    """异步主函数 — 整个进程共用一个 event loop"""
    agent = LongAgent.create(config_path=config)
    shutdown = GracefulShutdown(agent)
    shutdown.register()

    try:
        if once:
            # 单条命令模式
            response = await agent.run(once)
            console.print(Markdown(response))
        else:
            # 交互式 REPL 模式
            console.print("Long Agent v1.0")
            console.print('输入 "帮助" 查看命令，输入 "退出" 结束对话。\n')

            while agent.is_running:
                try:
                    # prompt-toolkit 异步输入
                    user_input = await async_input("> ")
                    if not user_input.strip():
                        continue
                    response = await agent.run(user_input)
                    console.print(Markdown(f"Agent: {response}"))
                except (EOFError, KeyboardInterrupt):
                    break
    finally:
        # 确保优雅关闭（只调用一次）
        await shutdown.shutdown()

@app.command()
def main(
    config: str = typer.Option(None, "--config", "-c"),
    once: str = typer.Option(None, "--once", "-o"),
    read_only: bool = typer.Option(False, "--read-only", "-r",
                                    help="只读模式：禁止写入记忆/修改配置"),
):
    """
    Long Agent — 个人 AI 助手

    --read-only 模式：
    - 允许：读取记忆、搜索、查看人格、查看配置
    - 禁止：写入记忆、修改人格、修改配置、删除数据、执行危险操作
    - 用途：多人共用 Agent 时，防止非主人修改核心数据
    """
    if read_only:
        logger.info("⚠️ 只读模式已启用：所有写入操作将被拒绝")
    # 整个进程只调用一次 asyncio.run()
    asyncio.run(async_main(config=config, once=once, read_only=read_only))

async async_input(prompt: str) -> str:
    """异步输入（不阻塞 event loop）"""
    return await asyncio.get_event_loop().run_in_executor(
        None, lambda: console.input(prompt)
    )
```

### 2.4 优雅关闭

```python
# src/entry/signals.py

import signal
import asyncio

class GracefulShutdown:
    """优雅关闭处理"""

    def __init__(self, agent: 'LongAgent'):
        self.agent = agent
        self._shutting_down = False

    def register(self):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        if self._shutting_down:
            return
        self._shutting_down = True
        console.print("\n正在关闭...")
        # 使用 create_task 而不是 asyncio.run()
        asyncio.ensure_future(self.agent.shutdown())

    async def shutdown(self):
        """
        优雅关闭流程：
        1. 停止接受新输入
        2. 等待当前对话完成（最多 10 秒）
        3. 保存所有未写入的记忆
        4. 执行关闭前维护（含备份）
        5. 关闭数据库连接
        """
        self.agent.stop_accepting_input()
        await asyncio.wait_for(self.agent.wait_current_turn(), timeout=10.0)
        self.agent.memory.flush_pending_writes()
        await self.agent.background.on_shutdown()  # 关闭前备份
        self.agent.memory.close()
```

### 2.5 库入口

```python
# src/entry/library.py

class LongAgent:
    """Long Agent — 库入口"""

    @classmethod
    def create(cls, config_path: str = None,
               read_only: bool = False) -> 'LongAgent':
        """
        工厂方法：创建并初始化 Agent

        Args:
            config_path: 配置文件路径
            read_only: 只读模式。True 时所有写入操作将被拒绝。
        """
        settings = Settings(_env_file=config_path)
        logger = init_logging(settings.log_level)
        db = DatabaseManager(settings.database_path)
        MigrationManager(db).migrate()
        memory = MemoryManager(db, settings.data_dir)
        llm = LLMProviderFactory.create(settings.llm_provider, **settings.llm_config)
        background = BackgroundTasks(memory)
        background.on_startup()  # 启动时检查备份状态
        agent = cls(settings, logger, db, memory, llm, background)
        agent.read_only = read_only
        if read_only:
            logger.info("⚠️ Agent 以只读模式启动")
        return agent

    async def run(self, user_input: str) -> str:
        return await self.loop.run(user_input)

    async def shutdown(self):
        await GracefulShutdown(self).shutdown()
```

---

## 三、Agent 状态机设计

> **红线 6：核心实体必须有状态机。** 主循环的 7 个步骤必须定义合法的状态转换，不允许任意跳转。

### 3.1 状态定义

```python
# src/loop/state.py

from enum import Enum

class AgentState(Enum):
    IDLE = "idle"                    # 空闲，等待用户输入
    PERCEIVING = "perceiving"        # ①感知：读取上下文
    UNDERSTANDING = "understanding"  # ②理解：解析意图
    PLANNING = "planning"            # ③规划：确定操作
    EXECUTING = "executing"          # ④执行：执行操作
    OBSERVING = "observing"          # ⑤观察：检查结果
    REFLECTING = "reflecting"        # ⑥反思：更新记忆
    REPLYING = "replying"            # ⑦回复：返回结果
    WAITING_APPROVAL = "waiting_approval"  # 等待用户审批
    CLARIFYING = "clarifying"        # 追问澄清
    FAILED = "failed"                # 失败，需要恢复
```

### 3.2 合法状态转换表

```
当前状态          → 可转入状态
─────────────────────────────────────────────────────
IDLE             → PERCEIVING（收到用户输入）
PERCEIVING       → UNDERSTANDING（上下文读取成功）
                   → FAILED（上下文读取失败）
UNDERSTANDING    → PLANNING（意图解析成功，置信度≥0.5）
                   → CLARIFYING（置信度<0.5，需要追问）
                   → FAILED（LLM 不可用/重试耗尽）
CLARIFYING       → UNDERSTANDING（用户回复后重新理解）
                   → FAILED（追问次数耗尽）
PLANNING         → EXECUTING（操作不需要审批/已批准）
                   → WAITING_APPROVAL（操作需要审批）
WAITING_APPROVAL → EXECUTING（用户批准）
                   → IDLE（用户拒绝/超时）
EXECUTING        → OBSERVING（执行成功）
                   → FAILED（执行错误且不可恢复）
OBSERVING        → REFLECTING（结果正常）
                   → EXECUTING（检测到跑偏，重试，最多2次）
                   → FAILED（跑偏重试耗尽）
REFLECTING       → REPLYING（记忆写入成功）
                   → REPLYING（记忆写入失败，已入队 pending_writes）
REPLYING         → IDLE（回复完成）
FAILED           → IDLE（返回错误信息给用户）
                   → REFLECTING（错误已记录，继续反思）
```

### 3.3 状态转换代码

```python
# src/loop/state_machine.py

class StateMachine:
    """Agent 状态机 — 强制合法转换"""

    TRANSITIONS: dict[AgentState, set[AgentState]] = {
        AgentState.IDLE: {AgentState.PERCEIVING},
        AgentState.PERCEIVING: {AgentState.UNDERSTANDING, AgentState.FAILED},
        AgentState.UNDERSTANDING: {
            AgentState.PLANNING, AgentState.CLARIFYING, AgentState.FAILED
        },
        AgentState.CLARIFYING: {AgentState.UNDERSTANDING, AgentState.FAILED},
        AgentState.PLANNING: {
            AgentState.EXECUTING, AgentState.WAITING_APPROVAL
        },
        AgentState.WAITING_APPROVAL: {AgentState.EXECUTING, AgentState.IDLE},
        AgentState.EXECUTING: {AgentState.OBSERVING, AgentState.FAILED},
        AgentState.OBSERVING: {
            AgentState.REFLECTING, AgentState.EXECUTING, AgentState.FAILED
        },
        AgentState.REFLECTING: {AgentState.REPLYING},
        AgentState.REPLYING: {AgentState.IDLE},
        AgentState.FAILED: {AgentState.IDLE, AgentState.REFLECTING},
    }

    def __init__(self):
        self.current_state = AgentState.IDLE
        self._history: list[tuple[AgentState, AgentState]] = []  # (from, to)

    def transition_to(self, new_state: AgentState) -> None:
        """执行状态转换，非法转换直接拒绝"""
        allowed = self.TRANSITIONS.get(self.current_state, set())
        if new_state not in allowed:
            raise IllegalStateTransitionError(
                f"非法状态转换：{self.current_state.value} → {new_state.value}。"
                f"允许的目标：{[s.value for s in allowed]}"
            )
        old_state = self.current_state
        self.current_state = new_state
        self._history.append((old_state, new_state))
        logger.debug(
            f"状态转换: {old_state.value} → {new_state.value}",
            extra={"event": "state_transition",
                   "from": old_state.value, "to": new_state.value}
        )

    def can_transition_to(self, new_state: AgentState) -> bool:
        """检查是否可以转换到目标状态"""
        return new_state in self.TRANSITIONS.get(self.current_state, set())
```

### 3.4 统一错误处理策略

> **反模式修复：** 当前代码中有些地方用 `raise`，有些用 `return action.user_message`，需要统一。

```python
# src/errors/handling.py

class ErrorHandlingPolicy:
    """
    统一错误处理策略

    三类错误，三种处理方式：

    ┌─────────────────┬──────────────────────────────────────────────────┐
    │ 错误类型         │ 处理方式                                         │
    ├─────────────────┼──────────────────────────────────────────────────┤
    │ 用户可见错误     │ return Result(is_error=True, user_message="...") │
    │ (输入非法/超时)  │ 不抛异常，给用户友好提示                         │
    ├─────────────────┼──────────────────────────────────────────────────┤
    │ 可恢复系统错误   │ 自动重试（指数退避），重试耗尽后转为用户可见错误  │
    │ (LLM超时/DB断开) │ 记录 warning 日志                                │
    ├─────────────────┼──────────────────────────────────────────────────┤
    │ 不可恢复系统错误 │ raise → 状态机转入 FAILED → 返回用户可见提示     │
    │ (状态机异常/     │ 记录 critical 日志                               │
    │  数据库损坏)     │ 不吞掉，让调用方知道                             │
    └─────────────────┴──────────────────────────────────────────────────┘

    规则：
    1. 永远不吞掉异常（至少记录日志）
    2. 永远不把原始异常暴露给用户（包装为友好提示）
    3. raise 只在"调用方需要知道"时使用
    4. return Result 只在"直接面对用户使用"时使用
    """

    @staticmethod
    def handle_user_error(message: str) -> Result:
        """用户可见错误：返回友好提示"""
        return Result(is_error=True, error_type="user", user_message=message)

    @staticmethod
    def handle_recoverable_error(e: Exception, attempt: int,
                                  max_retries: int) -> bool:
        """
        可恢复系统错误：决定是否重试

        Returns:
            True = 继续重试，False = 重试耗尽，转为用户可见错误
        """
        if attempt < max_retries:
            wait_time = min(2 ** attempt, 30)  # 指数退避，最多30秒
            logger.warning(
                f"可恢复错误（第 {attempt+1}/{max_retries} 次），"
                f"{wait_time}s 后重试: {e}"
            )
            return True
        else:
            logger.error(f"重试耗尽（{max_retries} 次）: {e}")
            return False

    @staticmethod
    def handle_fatal_error(e: Exception) -> Result:
        """不可恢复系统错误：记录 critical + 返回用户可见提示"""
        logger.critical(
            f"不可恢复错误: {type(e).__name__}: {e}",
            exc_info=True  # 记录完整堆栈
        )
        return Result(
            is_error=True,
            error_type="system",
            user_message="系统内部错误，请重启 Agent。如果持续出现，请检查日志。"
        )
```

### 3.5 主循环与状态机集成

```python
# src/loop/agent_loop.py

class AgentLoop:
    """Agent 主循环 — 与状态机集成"""

    def __init__(self, ...):
        self.state_machine = StateMachine()
        # ... 其他初始化

    async def run(self, user_input: str) -> str:
        """执行一次完整的 Agent 循环"""
        try:
            # ① 感知
            self.state_machine.transition_to(AgentState.PERCEIVING)
            context = await self.memory.build_context()

            # ② 理解
            self.state_machine.transition_to(AgentState.UNDERSTANDING)
            intent = await self._understand_with_retry(user_input, context)
            if intent is None:
                self.state_machine.transition_to(AgentState.FAILED)
                return self._handle_failure(LLMUnavailableError)
            if intent.confidence < 0.50:
                self.state_machine.transition_to(AgentState.CLARIFYING)
                return await self._clarify(user_input, intent)

            # ③ 规划
            self.state_machine.transition_to(AgentState.PLANNING)
            operation = self._plan(intent, context)
            if operation.requires_approval:
                self.state_machine.transition_to(AgentState.WAITING_APPROVAL)
                approved = await self.security.request_approval(operation)
                if not approved:
                    self.state_machine.transition_to(AgentState.IDLE)
                    return "操作已取消。"
                self.state_machine.transition_to(AgentState.EXECUTING)

            # ④ 执行
            else:
                self.state_machine.transition_to(AgentState.EXECUTING)
            result = await self._execute_with_error_handling(operation)
            if result.is_error:
                self.state_machine.transition_to(AgentState.FAILED)
                return self._handle_failure(result)

            # ⑤ 观察
            self.state_machine.transition_to(AgentState.OBSERVING)
            off_track_retries = 0
            while self._is_off_track(result, intent) and off_track_retries < self.MAX_OFF_TRACK_RETRIES:
                off_track_retries += 1
                self.state_machine.transition_to(AgentState.EXECUTING)
                result = await self._execute_with_error_handling(operation)
                self.state_machine.transition_to(AgentState.OBSERVING)

            if off_track_retries >= self.MAX_OFF_TRACK_RETRIES:
                self.state_machine.transition_to(AgentState.FAILED)
                return self._handle_failure(OffTrackError)

            # ⑥ 反思
            self.state_machine.transition_to(AgentState.REFLECTING)
            await self._reflect_with_retry(user_input, result, intent)

            # ⑦ 回复
            self.state_machine.transition_to(AgentState.REPLYING)
            response = result.content
            self.state_machine.transition_to(AgentState.IDLE)
            return response

        except IllegalStateTransitionError as e:
            logger.critical(f"状态机异常: {e}")
            self.state_machine.transition_to(AgentState.FAILED)
            return "系统内部错误，请重启 Agent。"
```

---

## 四、Agent 主循环设计

### 4.1 V1 执行范围声明

> **V1 阶段只支持记忆读写操作，不支持通用工具调用。**
>
> V1 的执行层仅能：
> - `memory_write`：写入三层记忆
> - `memory_read`：读取三层记忆
> - `memory_search`：全文搜索记忆
> - `personality_update`：调整 HEXACO 人格值
>
> V2 才扩展为通用工具调用。

### 3.2 7 步循环（含错误恢复 + 错误分类）

> 与 v1.2 版本相同，已在第六节完善错误分类（含 context_overflow 处理）。

### 3.3 本地规则 vs LLM 调用

```python
# src/main.py

LOCAL_RULES = {
    "停": "interrupt", "退出": "exit", "帮助": "help",
    "你是谁": "who_are_you", "现在几点": "current_time",
    "清空记忆": "clear_memory", "重置人格": "reset_personality",
    "查看记忆": "show_memory", "查看人格": "show_personality",
}

def should_call_llm(user_input: str) -> bool:
    """本地规则能处理 → 不调 LLM；其他一切 → 调 LLM"""
    return user_input.strip() not in LOCAL_RULES
```

### 3.4 主循环代码结构

```python
# src/loop/agent_loop.py

class AgentLoop:
    """Agent 主循环 — V1"""

    MAX_LLM_RETRIES = 3
    LLM_TIMEOUT = 30
    MAX_CLARIFICATION_ROUNDS = 3
    MAX_OFF_TRACK_RETRIES = 2

    def __init__(self, memory, understanding, security, llm, error_classifier):
        self.memory = memory
        self.understanding = understanding
        self.security = security
        self.llm = llm
        self.error_classifier = error_classifier

    async def run(self, user_input: str) -> str:
        """执行一次完整的 Agent 循环"""
        # ① 感知
        context = self.memory.build_context()

        # ② 理解（含错误分类 + 重试）
        if not should_call_llm(user_input):
            return self._handle_local_rule(user_input)
        intent = await self._understand_with_retry(user_input, context)
        if intent is None:
            return self.error_classifier.get_user_message(LLMUnavailableError)
        if intent.confidence < 0.50:
            return await self._clarify(user_input, intent)

        # ③ 规划
        operation = self._plan(intent, context)
        if operation.requires_approval:
            approved = await self.security.request_approval(operation)
            if not approved:
                return "操作已取消。"

        # ④ 执行（含错误恢复）
        result = await self._execute_with_error_handling(operation)
        if result.is_error:
            return result.user_message

        # ⑤ 观察
        off_track_retries = 0
        while self._is_off_track_simple(result, intent) and off_track_retries < self.MAX_OFF_TRACK_RETRIES:
            off_track_retries += 1
            intent = await self._understand_with_retry(user_input, context)
            if intent is None:
                break
            result = await self._execute_with_error_handling(operation)

        # ⑥ 反思
        await self._reflect_with_retry(user_input, result, intent)

        # ⑦ 回复
        return result.content

    async def _understand_with_retry(self, user_input, context) -> Optional[Intent]:
        """带重试的意图理解（按错误分类决定是否重试）"""
        for attempt in range(self.MAX_LLM_RETRIES):
            try:
                return await self.understanding.parse(user_input, context)
            except LLMError as e:
                action = self.error_classifier.classify(e)
                if action.should_retry and attempt < action.max_retries - 1:
                    wait_time = action.get_wait_time(attempt)
                    logger.warning(f"LLM 错误（第 {attempt+1} 次），{wait_time}s 后重试: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"不可重试错误或重试耗尽: {e}")
                    return None
        return None

    async def _execute_with_error_handling(self, operation: Operation) -> Result:
        """带错误恢复的执行"""
        try:
            handler = self._get_operation_handler(operation.type)
            return await handler(operation)
        except DatabaseError as e:
            logger.error(f"数据库错误: {e}")
            return Result(is_error=True, error_type="database",
                         user_message="操作失败，请重试。如果持续出现，请检查数据库连接。")
        except Exception as e:
            logger.error(f"执行错误: {e}")
            return Result(is_error=True, error_type="unknown",
                         user_message=f"操作出错：{type(e).__name__}，请重试。")

    async def _reflect_with_retry(self, user_input, result, intent):
        """带错误恢复的反思"""
        try:
            self.memory.learn(user_input, result, intent)
            self.memory.update_personality(user_input, result)
        except Exception as e:
            logger.error(f"记忆写入失败，已入队: {e}")
            self.memory.pending_write(user_input, result, intent)

    def _plan(self, intent, context) -> Operation:
        """V1 规划：简化为操作描述"""
        return Operation(
            type=self._intent_to_operation_type(intent),
            layer=intent.target_layer,
            content=intent.content,
            requires_approval=self.security.requires_approval(intent),
        )

    def _is_off_track_simple(self, result, intent) -> bool:
        """V1 跑偏检查：置信度 + 关键词"""
        if result.confidence < 0.5:
            return True
        fuzzy_words = ["不确定", "可能", "大概", "也许", "或许", "应该"]
        return any(w in result.content for w in fuzzy_words)
```

---

## 五、上下文管理

> 参考来源：多算法融合上下文压缩引擎（`自己开发的模块/context_compressor.md`）

### 4.1 多算法融合压缩引擎概述

**核心思路：不依赖单一算法，融合 10 种算法对每条消息评分，保留高价值消息，压缩低价值消息。**

```
消息输入
    │
    ▼
┌─────────────────────────────────────────────────┐
│  1. 对话结构分析器                               │
│     识别 thread 结构，标记追问-根问答关系         │
├─────────────────────────────────────────────────┤
│  2. 用户模式学习器                               │
│     学习用户对话模式，返回自适应压缩参数          │
│     v1.1：基于历史百分位数动态计算               │
├─────────────────────────────────────────────────┤
│  3. 跨轮次实体追踪器                             │
│     追踪人/项目/概念的跨轮次引用                  │
├─────────────────────────────────────────────────┤
│  4. 10 算法融合评分引擎                          │
│     信息熵(香农) + 遗忘曲线(艾宾浩斯)            │
│     + 序参量(协同学) + 突变点(突变论)            │
│     + PageRank + 矛盾检测(自指性)                │
│     + 混沌边缘动态权重 + 情感权重(含否定检测)    │
│     + 跨轮次实体保留                             │
├─────────────────────────────────────────────────┤
│  5. 幂律分布裁剪器                               │
│     v1.1：二阶导数最大点（曲率拐点）             │
├─────────────────────────────────────────────────┤
│  6. LLM 摘要 + 自指性递归验证                    │
│     v1.1：基于覆盖率自适应次数（1-3次）          │
├─────────────────────────────────────────────────┤
│  7. 压缩质量反馈器                               │
│     评估压缩质量，动态调整阈值                    │
└─────────────────────────────────────────────────┘
    │
    ▼
压缩后消息输出
```

**算法权重分配（初始默认值，运行时通过贝叶斯优化自动调优）：**

| 算法 | 初始权重 | 自适应方法 | 科学依据 |
|------|---------|-----------|---------|
| 序参量关联 | 0.25 | 贝叶斯优化（高斯过程） | 协同学支配原理 |
| 信息熵 | 0.20 | 贝叶斯优化（高斯过程） | 香农信息论 |
| 突变点 | 0.15 | 贝叶斯优化（高斯过程） | 突变论 |
| 遗忘曲线 | 0.15 | 贝叶斯优化（高斯过程） | 耗散结构 + 艾宾浩斯 |
| PageRank | 0.10 | 贝叶斯优化（高斯过程） | 图算法 |
| 矛盾检测 | 0.10 | 贝叶斯优化（高斯过程） | 自指性理论 |
| 跨轮次实体 | 0.05 | 贝叶斯优化（高斯过程） | 信息检索 |
| 情感权重 | 动态乘数 | 实时计算 | 心理学 |
| 混沌边缘 | 动态调整 | Sigmoid 函数 | 复杂系统 |

> **设计原则**：初始权重基于科学依据，但不同用户/场景下最优权重不同。V2 通过贝叶斯优化（目标函数=用户满意度）自动搜索最优权重组合。

### 4.2 Token 精确计算

> 使用 tiktoken 精确计算，不使用 chars // 4 估算。

```python
# src/understanding/token_counter.py

import tiktoken
from src.llm.model_registry import get_model_spec

class TokenCounter:
    """Token 精确计算器"""

    def __init__(self, model_name: str = "gpt-4o"):
        spec = get_model_spec(model_name)
        self._encoding = tiktoken.get_encoding(spec.encoding)
        self.max_input_tokens = spec.max_input_tokens

    def count_tokens(self, messages: list[dict]) -> int:
        """精确计算消息列表的 token 数"""
        return sum(
            len(self._encoding.encode(m.get("content", "")))
            for m in messages
        )

    def should_compress(self, messages: list[dict],
                        max_messages: int = 20,
                        max_tokens: int = 80000) -> bool:
        """判断是否需要压缩"""
        if len(messages) > max_messages:
            return True
        if self.count_tokens(messages) > max_tokens:
            return True
        return False
```

### 4.3 主压缩引擎接口

```python
# src/understanding/context_compressor.py

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class MessageScore:
    """一条消息的综合评分"""
    message: dict
    index: int
    entropy_score: float = 0.0        # 信息熵（香农）
    forgetting_score: float = 0.0     # 遗忘曲线（艾宾浩斯）
    order_param_score: float = 0.0    # 序参量关联（协同学）
    mutation_score: float = 0.0       # 突变点（突变论）
    pagerank_score: float = 0.0       # PageRank 影响力
    contradiction_score: float = 0.0  # 冗余检测（自指性）
    emotional_multiplier: float = 1.0 # 情感权重乘数
    entity_score: float = 0.0         # 跨轮次实体保留
    final_score: float = 0.0          # 综合得分
    keep: bool = False                # 是否保留
    keep_reasons: list = field(default_factory=list)


class MultiAlgorithmCompressor:
    """
    多算法融合上下文压缩引擎 — V1.1

    完整实现约 2800-3200 行（含注释），
    详见 `自己开发的模块/context_compressor.md`

    子模块：
    - DialogueStructureAnalyzer  — 对话结构分析
    - UserDialogueModel          — 用户模式学习（百分位数自适应）
    - CrossTurnEntityTracker     — 跨轮次实体追踪
    - PowerLawPruner             — 幂律裁剪（二阶导数拐点）
    - EmotionalWeightAnalyzer    — 情感权重（否定词检测+强度分级）
    - CompressionQualityFeedback — 压缩质量反馈
    """

    PROTECT_FIRST_N = 3
    PROTECT_LAST_N = 6

    def __init__(self, llm_client, logger=None):
        self.llm = llm_client
        self.logger = logger
        # 子模块实例化...

    async def compress(self, messages: list[dict]) -> list[dict]:
        """
        主压缩流程（12 步）：
        1.  保护头尾消息
        2.  对话结构分析（thread 识别）
        3.  用户模式学习（自适应参数）
        4.  跨轮次实体追踪
        5.  提取全局特征（序参量、突变点）
        6.  构建消息引用图（PageRank）
        7.  对每条消息 10 算法评分
        8.  混沌边缘动态调整权重（连续 sigmoid）
        9.  综合评分 + 幂律裁剪（二阶导数拐点）
        10. 低分消息 → LLM 摘要
        11. 自指性递归验证（自适应 1-3 次）
        12. 压缩质量反馈
        """
        ...

    def should_compress(self, messages: list[dict]) -> bool:
        """判断是否需要压缩"""
        ...
```

### 4.4 在主循环中的使用

```python
# 在 Agent 主循环的感知阶段使用

compressor = MultiAlgorithmCompressor(llm_client=agent.llm)
token_counter = TokenCounter(model_name=agent.settings.openai_model)

# ① 感知阶段：组装消息后检查是否需要压缩
messages = context.build_messages()

if token_counter.should_compress(messages):
    messages = await compressor.compress(messages)

# ② 理解阶段：用压缩后的消息调 LLM
intent = await understanding.parse(user_input, messages)
```

---

## 六、LLM 调用层设计

> 设计来源：自主设计 — LLMProvider 抽象接口 + 模型注册表 + 流式输出

### 5.1 模型注册表

> **修复问题**：model_name 和 max_context_tokens 从配置读取，不硬编码。

```python
# src/llm/model_registry.py

from dataclasses import dataclass

@dataclass(frozen=True)
class ModelSpec:
    """模型规格"""
    model_name: str
    max_input_tokens: int      # 输入上下文窗口
    max_output_tokens: int     # 最大输出 tokens
    supports_streaming: bool
    supports_function_calling: bool
    encoding: str              # tiktoken 编码名

# 模型注册表：所有支持的模型规格集中管理
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "gpt-4o": ModelSpec(
        model_name="gpt-4o",
        max_input_tokens=128000,
        max_output_tokens=16384,
        supports_streaming=True,
        supports_function_calling=True,
        encoding="o200k_base",       # gpt-4o 使用 o200k_base 编码
    ),
    "gpt-4o-mini": ModelSpec(
        model_name="gpt-4o-mini",
        max_input_tokens=128000,
        max_output_tokens=16384,
        supports_streaming=True,
        supports_function_calling=True,
        encoding="o200k_base",
    ),
    # V2 扩展：
    # "claude-3-5-sonnet": ModelSpec(
    #     model_name="claude-3-5-sonnet-20241022",
    #     max_input_tokens=200000,
    #     max_output_tokens=8192,
    #     supports_streaming=True,
    #     supports_function_calling=True,  # Anthropic 叫 tool_use
    #     encoding="cl100k_base",  # 用 cl100k_base 近似
    # ),
}

def get_model_spec(model_name: str) -> ModelSpec:
    """获取模型规格"""
    if model_name not in MODEL_REGISTRY:
        raise ValueError(
            f"未知模型: {model_name}。"
            f"可用模型: {list(MODEL_REGISTRY.keys())}"
        )
    return MODEL_REGISTRY[model_name]
```

### 5.2 统一接口

```python
# src/llm/base.py

from abc import ABC, abstractmethod
from .model_registry import ModelSpec

class LLMProvider(ABC):
    """
    LLM 提供商统一接口

    设计思路：接口与实现分离——
    引擎不依赖具体 LLM 提供商，提供商通过统一接口接入。
    """

    @property
    @abstractmethod
    def spec(self) -> ModelSpec:
        """模型规格（从注册表读取，不硬编码）"""
        ...

    @abstractmethod
    async def chat(self, messages: list[dict],
                   temperature: float = 0.7) -> LLMResponse:
        """非流式调用"""
        ...

    @abstractmethod
    async def stream(self, messages: list[dict],
                     temperature: float = 0.7) -> AsyncIterator[str]:
        """流式调用，逐 token 返回"""
        ...

    def count_tokens(self, messages: list[dict]) -> int:
        """
        精确计算 token 数

        默认实现使用 tiktoken，子类可以覆盖。
        比 chars // 4 精确得多：
        - gpt-4o 用 o200k_base 编码
        - 不再区分中英文比例，直接精确编码
        """
        import tiktoken
        encoding = tiktoken.get_encoding(self.spec.encoding)
        return sum(
            len(encoding.encode(m.get("content", "")))
            for m in messages
        )
```

### 5.3 OpenAI 实现

```python
# src/llm/openai_provider.py

import time
import tiktoken
from openai import AsyncOpenAI
from .base import LLMProvider, LLMResponse
from .model_registry import get_model_spec

class OpenAIProvider(LLMProvider):
    """OpenAI 实现"""

    def __init__(self, api_key: str, model: str = "gpt-4o",
                 timeout: int = 30, max_retries: int = 3):
        self.client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._model = model
        # 从注册表读取模型规格，不硬编码
        self._spec = get_model_spec(model)

    @property
    def spec(self) -> ModelSpec:
        return self._spec

    async def chat(self, messages: list[dict],
                   temperature: float = 0.7) -> LLMResponse:
        start = time.perf_counter()
        response = await self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=self._spec.max_output_tokens,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        return LLMResponse(
            content=response.choices[0].message.content,
            tokens_used=response.usage.total_tokens,
            model=self._model,
            latency_ms=round(latency_ms, 2),
        )

    async def stream(self, messages: list[dict],
                     temperature: float = 0.7) -> AsyncIterator[str]:
        """流式调用，逐 token 返回"""
        stream = await self.client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=self._spec.max_output_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def count_tokens(self, messages: list[dict]) -> int:
        """使用 tiktoken 精确计算（用模型对应的编码）"""
        encoding = tiktoken.get_encoding(self._spec.encoding)
        return sum(
            len(encoding.encode(m.get("content", "")))
            for m in messages
        )
```

### 5.4 提供商工厂

```python
# src/llm/factory.py

class LLMProviderFactory:
    """LLM 提供商工厂"""

    _providers = {
        "openai": OpenAIProvider,
    }

    @classmethod
    def create(cls, provider: str, **kwargs) -> LLMProvider:
        if provider not in cls._providers:
            raise ValueError(
                f"不支持的 LLM 提供商: {provider}，"
                f"可用: {list(cls._providers.keys())}"
            )
        return cls._providers[provider](**kwargs)
```

### 5.5 流式输出到终端

```python
# src/output/stream_printer.py

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

class StreamPrinter:
    """流式输出到终端"""

    def __init__(self):
        self.console = Console()

    async def print_stream(self, stream: AsyncIterator[str]):
        content = ""
        with Live(Markdown(""), console=self.console, refresh_per_second=10) as live:
            async for chunk in stream:
                content += chunk
                live.update(Markdown(f"Agent: {content}"))
```

---

## 七、错误分类与恢复

> 设计来源：自主设计 — 6 种错误分类 + 对应恢复动作 + context_overflow 分支

### 6.1 错误分类体系（含 context_overflow）

```python
# src/errors/classifier.py

from enum import Enum
from dataclasses import dataclass

class ErrorCategory(Enum):
    RETRYABLE = "retryable"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    CONTENT_FILTER = "content_filter"
    CONTEXT_OVERFLOW = "context_overflow"  # ← 已覆盖
    DATABASE = "database"
    UNKNOWN = "unknown"

@dataclass
class ErrorAction:
    category: ErrorCategory
    should_retry: bool
    max_retries: int
    base_wait_seconds: float
    user_message: str          # 包含"出了什么"和"怎么解决"
    recovery_action: str       # 恢复动作：retry / compress_and_retry / stop

class ErrorClassifier:
    """错误分类器"""

    HTTP_ERROR_MAP = {
        401: ErrorAction(
            category=ErrorCategory.AUTH,
            should_retry=False, max_retries=0, base_wait_seconds=0,
            user_message="API Key 无效。请检查配置文件中的 OPENAI_API_KEY 是否正确。",
            recovery_action="stop",
        ),
        403: ErrorAction(
            category=ErrorCategory.AUTH,
            should_retry=False, max_retries=0, base_wait_seconds=0,
            user_message="API Key 权限不足。请检查 Key 是否有对应模型的访问权限。",
            recovery_action="stop",
        ),
        429: ErrorAction(
            category=ErrorCategory.RATE_LIMIT,
            should_retry=True, max_retries=5, base_wait_seconds=60,
            user_message="请求太频繁，已限流。正在等待后重试...",
            recovery_action="retry",
        ),
        500: ErrorAction(
            category=ErrorCategory.RETRYABLE,
            should_retry=True, max_retries=3, base_wait_seconds=2,
            user_message="OpenAI 服务暂时不可用，正在重试...",
            recovery_action="retry",
        ),
        503: ErrorAction(
            category=ErrorCategory.RETRYABLE,
            should_retry=True, max_retries=3, base_wait_seconds=5,
            user_message="OpenAI 服务暂时不可用，正在重试...",
            recovery_action="retry",
        ),
    }

    # context_overflow 的关键词模式
    CONTEXT_OVERFLOW_PATTERNS = [
        "context length", "maximum context", "context too long",
        "token limit", "max_tokens", "exceeds.*token",
        "请求长度超过", "上下文过长", "超出.*限制",
    ]

    def classify(self, error: Exception) -> ErrorAction:
        """
        分类错误，返回恢复动作

        优先级：HTTP 状态码 → context_overflow 关键词 → 连接/超时 → 数据库 → 未知
        """
        error_text = str(error).lower()

        # 1. HTTP 状态码
        if hasattr(error, "status_code"):
            status = error.status_code
            if status in self.HTTP_ERROR_MAP:
                return self.HTTP_ERROR_MAP[status]

        # 2. context_overflow 关键词匹配
        import re
        for pattern in self.CONTEXT_OVERFLOW_PATTERNS:
            if re.search(pattern, error_text):
                return ErrorAction(
                    category=ErrorCategory.CONTEXT_OVERFLOW,
                    should_retry=True, max_retries=1, base_wait_seconds=0,
                    user_message="对话历史过长，正在压缩后重试...",
                    recovery_action="compress_and_retry",  # 触发上下文压缩后重试
                )

        # 3. 连接/超时错误
        if isinstance(error, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
            return ErrorAction(
                category=ErrorCategory.RETRYABLE,
                should_retry=True, max_retries=3, base_wait_seconds=1,
                user_message="网络连接超时，正在重试...",
                recovery_action="retry",
            )

        # 4. 数据库错误
        if isinstance(error, sqlite3.Error):
            return ErrorAction(
                category=ErrorCategory.DATABASE,
                should_retry=False, max_retries=0, base_wait_seconds=0,
                user_message="数据库操作失败。请检查数据库文件是否损坏："
                           f"{error_text}",
                recovery_action="stop",
            )

        # 5. 未知错误
        return ErrorAction(
            category=ErrorCategory.UNKNOWN,
            should_retry=False, max_retries=0, base_wait_seconds=0,
            user_message=f"发生未知错误：{type(error).__name__}。请重试。",
            recovery_action="stop",
        )
```

### 6.2 context_overflow 恢复流程

```python
# 在主循环的错误恢复中处理 compress_and_retry

async def _understand_with_retry(self, user_input, context) -> Optional[Intent]:
    for attempt in range(self.MAX_LLM_RETRIES):
        try:
            return await self.understanding.parse(user_input, context)
        except LLMError as e:
            action = self.error_classifier.classify(e)
            if action.recovery_action == "compress_and_retry":
                # context_overflow → 压缩上下文后重试
                logger.warning("检测到上下文溢出，触发压缩")
                context.messages = await self.understanding.context_compressor.compress(
                    context.messages
                )
                # 压缩后直接重试（不消耗重试次数）
                try:
                    return await self.understanding.parse(user_input, context)
                except LLMError:
                    pass  # 压缩后还是失败，走正常重试逻辑
            elif action.should_retry and attempt < action.max_retries - 1:
                wait_time = action.get_wait_time(attempt)
                await asyncio.sleep(wait_time)
            else:
                return None
    return None
```

---

## 八、后台任务

> 设计来源：自主设计 — 纯事件驱动（对话后触发 + 启动时检查 + 关闭前备份），不依赖定时器

### 7.1 后台任务设计（纯事件驱动，不依赖定时）

> **设计原则**：软件无法保证 24 小时在线，不能用固定时间触发备份。
> 所有维护操作由事件触发 + 时间间隔检查驱动。

```python
# src/background/manager.py

import asyncio
import json
import time
from pathlib import Path

class BackgroundTasks:
    """
    后台任务管理器 — V1

    策略（纯事件驱动，不依赖定时器）：
    1. 对话后触发：轻量级维护（访问计数衰减 + 按频率检查备份/快照清理/VACUUM）
    2. 启动时检查：距上次备份 > 48h → 提醒用户
    3. 关闭前触发：必须执行一次备份

    三个维护操作频率不同，分开判断：
    - 备份：每 24 小时一次（耗时短）
    - 快照清理：每 7 天一次（判断简单）
    - VACUUM：每 30 天一次（耗时长，不能每次备份都跑）
    """

    def __init__(self, memory: MemoryManager,
                 backup_interval_hours: int = 24,
                 snapshot_cleanup_days: int = 7,
                 vacuum_interval_days: int = 30):
        self.memory = memory
        self._meta_path = Path("data/backups/maintenance_meta.json")
        self._meta = self._read_meta()
        self._backup_interval = backup_interval_hours * 3600
        self._snapshot_interval = snapshot_cleanup_days * 86400
        self._vacuum_interval = vacuum_interval_days * 86400

    def _read_meta(self) -> dict:
        """读取维护元数据（记录各项操作上次执行时间）"""
        try:
            with open(self._meta_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return {
                "last_backup": 0.0,
                "last_snapshot_cleanup": 0.0,
                "last_vacuum": 0.0,
            }

    def _write_meta(self):
        """持久化维护元数据"""
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._meta_path, "w") as f:
            json.dump(self._meta, f, indent=2)

    def _elapsed(self, key: str) -> float:
        """距上次执行的秒数"""
        return time.time() - self._meta.get(key, 0.0)

    # ---- 启动时检查 ----

    def on_startup(self):
        """
        启动时检查：距上次备份超过 48 小时 → 提醒用户
        """
        elapsed = self._elapsed("last_backup")
        if elapsed > 48 * 3600:
            logger.warning(
                f"距上次备份已超过 {elapsed/3600:.0f} 小时，"
                f"建议手动备份或等待自动触发"
            )

    # ---- 对话后触发（轻量级，按频率分开判断） ----

    async def on_conversation_end(self):
        """
        每次对话结束后调用。
        三个维护操作频率不同，各自独立判断。
        """
        # 访问计数衰减（每次对话后执行，轻量）
        self.memory.decay_access_counts(factor=0.9)

        # 冷区压缩检查（判断条件，满足才执行）
        if self.memory.should_compress_cold_zone():
            self.memory.compress_cold_zone()

        # 备份检查（每 24h 一次）
        if self._elapsed("last_backup") > self._backup_interval:
            logger.info("执行数据备份")
            self.memory.backup(keep=3)
            self._meta["last_backup"] = time.time()
            self._write_meta()

        # 快照清理检查（每 7 天一次）
        if self._elapsed("last_snapshot_cleanup") > self._snapshot_interval:
            logger.info("执行快照清理")
            self.memory.cleanup_old_snapshots(days=7)
            self._meta["last_snapshot_cleanup"] = time.time()
            self._write_meta()

        # VACUUM 检查（每 30 天一次）
        if self._elapsed("last_vacuum") > self._vacuum_interval:
            logger.info("执行 SQLite VACUUM")
            self.memory.vacuum()
            self._meta["last_vacuum"] = time.time()
            self._write_meta()

    # ---- 关闭前触发（必须执行备份） ----

    async def on_shutdown(self):
        """
        优雅关闭前调用：必须执行一次备份
        """
        logger.info("关闭前维护：执行备份")
        self.memory.backup(keep=3)
        self._meta["last_backup"] = time.time()
        self._write_meta()
```

---

## 九、记忆系统（含存储抽象 + 数据备份）

> 设计来源：自主设计 — 存储抽象层（MemoryStorage 接口 + SQLiteStorage 实现）+ 事件驱动备份策略

### 8.1 存储抽象层

> **修复问题**：MVP 用 SQLite，但存储层抽象出来，V2 加 Redis 不改业务逻辑。

```python
# src/memory/storage/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class BatchWriteResult:
    """批量写入结果"""
    success_count: int = 0
    failed_count: int = 0
    failed_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class MemoryStorage(ABC):
    """
    记忆存储抽象接口

    MVP：SQLite 实现
    V2：Redis 实现（热区缓存）+ SQLite 实现（持久化）
    """

    @abstractmethod
    async def get(self, memory_id: str) -> Optional[Memory]: ...

    @abstractmethod
    async def find_by_content(self, content: str, layer: str = None) -> Optional[Memory]:
        """
        精确匹配内容（用于幂等性检查）

        Returns:
            找到返回 Memory，未找到返回 None
        """
        ...

    @abstractmethod
    async def search(self, query: str, layer: str = None,
                     limit: int = 10) -> list[Memory]: ...

    @abstractmethod
    async def upsert(self, memory: Memory) -> MemoryWriteResult: ...

    @abstractmethod
    async def delete(self, memory_id: str) -> bool: ...

    @abstractmethod
    async def count(self, layer: str = None) -> int: ...

    # ---- 批量操作 ----

    @abstractmethod
    async def batch_upsert(self, memories: list[Memory]) -> BatchWriteResult: ...

    @abstractmethod
    async def batch_get(self, memory_ids: list[str]) -> list[Memory]: ...

    @abstractmethod
    async def batch_update_access_counts(self, updates: dict[str, int]): ...

    @abstractmethod
    async def get_by_zone(self, zone: str, limit: int = 100) -> list[Memory]: ...

    @abstractmethod
    async def update_access_count(self, memory_id: str, delta: int = 1): ...

    @abstractmethod
    async def decay_all_access_counts(self, factor: float = 0.9): ...

    @abstractmethod
    async def get_old_snapshots(self, days: int = 7) -> list[Snapshot]: ...

    @abstractmethod
    async def delete_snapshots(self, snapshot_ids: list[str]): ...

    @abstractmethod
    async def vacuum(self): ...

    @abstractmethod
    def backup(self, backup_path: str) -> str:
        """返回备份文件路径"""
        ...

    @abstractmethod
    def close(self): ...

    # ---- 事务支持 ----

    @abstractmethod
    async def begin_transaction(self): ...

    @abstractmethod
    async def commit(self): ...

    @abstractmethod
    async def rollback(self): ...
```

### 8.2 SQLite 存储实现

```python
# src/memory/storage/sqlite_storage.py

import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from .base import MemoryStorage

class SQLiteStorage(MemoryStorage):
    """SQLite 存储实现 — MVP（跨平台）"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")  # WAL 模式提升并发
        self._init_tables()

        # 设置数据库文件权限（跨平台）
        # Linux/macOS: os.chmod(0o600)
        # Windows: icacls 命令
        self._set_file_permission(db_path)

    @staticmethod
    def _set_file_permission(path: str):
        """
        设置文件为仅当前用户可读写（跨平台）

        失败时记录警告日志，不阻塞主流程。
        """
        import platform
        import subprocess

        system = platform.system()
        try:
            if system in ("Linux", "Darwin"):
                os.chmod(path, 0o600)
            elif system == "Windows":
                subprocess.run(
                    ["icacls", path, "/reset", "/Q"],
                    capture_output=True, timeout=10
                )
                subprocess.run(
                    ["icacls", path, "/grant", f"{os.getlogin()}:F", "/Q"],
                    capture_output=True, timeout=10
                )
                subprocess.run(
                    ["icacls", path, "/inheritance:r", "/Q"],
                    capture_output=True, timeout=10
                )
            else:
                logger.warning(f"未知操作系统 {system}，跳过文件权限设置: {path}")
        except Exception as e:
            logger.warning(
                f"设置文件权限失败（{system}）: {path} — {e}。"
                f"请手动确保该文件不被其他用户访问。"
            )

    def backup(self, backup_dir: str = "data/backups",
               keep: int = 3) -> str:
        """
        数据备份：使用 SQLite 在线备份 API

        策略：
        1. 使用 sqlite3 的 .backup() API（在线备份，不锁表）
        2. 保留最近 N 个备份
        3. 备份文件名带时间戳
        """
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"memory_{timestamp}.db"

        # SQLite 在线备份
        backup_conn = sqlite3.connect(str(backup_path))
        self.conn.backup(backup_conn)
        backup_conn.close()

        # 清理旧备份：只保留最近 N 个
        backups = sorted(backup_dir.glob("memory_*.db"))
        for old_backup in backups[:-keep]:
            old_backup.unlink()
            logger.info(f"清理旧备份: {old_backup}")

        logger.info(f"备份完成: {backup_path}")
        return str(backup_path)

    def vacuum(self):
        """SQLite VACUUM：回收空间、优化数据库"""
        self.conn.execute("VACUUM")

    # ... 其他方法实现 ...
```

### 8.3 记忆管理器（使用存储抽象）

```python
# src/memory/manager.py

class MemoryManager:
    """
    记忆系统 — 统一入口

    通过 MemoryStorage 抽象接口操作数据，不依赖具体存储实现。
    V2 切换为 Redis 时，只需更换 storage 实现，此类代码不变。
    """

    def __init__(self, storage: MemoryStorage, data_dir: str):
        self.storage = storage
        self.data_dir = Path(data_dir)
        self.personality = self._load_personality()
        self.standards = self._load_standards()

    # ---- personality.md Schema 校验 ----

    REQUIRED_DIMENSIONS = {
        "H": {"name": "诚实-谦逊", "min": 0, "max": 100},
        "E": {"name": "情绪性",     "min": 0, "max": 100},
        "X": {"name": "外向性",     "min": 0, "max": 100},
        "A": {"name": "宜人性",     "min": 0, "max": 100},
        "C": {"name": "尽责性",     "min": 0, "max": 100},
        "O": {"name": "经验开放性", "min": 0, "max": 100},
    }

    def _load_personality(self) -> dict:
        """
        加载并校验 personality.md（防御性编程：校验失败降级到默认人格）

        格式要求：
        1. 必须是 Markdown 表格
        2. 必须有 6 行（H/E/X/A/C/O）
        3. 分值必须是 0-100 的整数

        校验失败处理策略（不阻塞启动）：
        - 文件不存在 → 返回默认人格（全50）
        - 解析失败/缺维度/分值非法 → 记录警告日志 + 返回默认人格
        - 个别维度分值非法 → 该维度用默认值50，其余正常加载
        """
        path = self.data_dir / "personality.md"
        if not path.exists():
            logger.info("personality.md 不存在，使用默认人格（全50）")
            return self._default_personality()

        # 尝试解析
        try:
            rows = self._parse_markdown_table(path)
        except Exception as e:
            logger.warning(
                f"personality.md 解析失败，使用默认人格：{e}。"
                f"请检查文件格式是否为有效的 Markdown 表格。"
            )
            return self._default_personality()

        # 提取维度分值
        result = {}
        errors = []
        for row in rows:
            dim_raw = row.get("维度", "").strip()
            score_raw = row.get("分值", "").strip()
            if not dim_raw:
                continue
            key = dim_raw[0].upper()
            if key not in self.REQUIRED_DIMENSIONS:
                continue

            try:
                score = int(score_raw)
            except (ValueError, TypeError):
                errors.append(
                    f"维度 {key} 分值 '{score_raw}' 不是整数，使用默认值50"
                )
                continue

            spec = self.REQUIRED_DIMENSIONS[key]
            if not (spec["min"] <= score <= spec["max"]):
                errors.append(
                    f"维度 {key}（{spec['name']}）分值 {score} 超出范围"
                    f"[{spec['min']}-{spec['max']}]，使用默认值50"
                )
                continue

            result[key] = score

        # 检查缺失维度
        missing = set(self.REQUIRED_DIMENSIONS.keys()) - set(result.keys())
        if missing:
            for key in missing:
                errors.append(
                    f"维度 {key}（{self.REQUIRED_DIMENSIONS[key]['name']}）"
                    f"缺失，使用默认值50"
                )

        # 有任何错误 → 记录警告 + 用默认值补全缺失维度
        if errors:
            logger.warning(
                f"personality.md 校验发现问题（{len(errors)}项），"
                f"已降级处理：{'; '.join(errors)}"
            )

        # 补全缺失维度（用默认值50）
        for key in self.REQUIRED_DIMENSIONS:
            if key not in result:
                result[key] = 50

        return result

    def _default_personality(self) -> dict:
        """默认人格：所有维度 50（中性）"""
        return {k: 50 for k in self.REQUIRED_DIMENSIONS}

    @staticmethod
    def _parse_markdown_table(path: Path) -> list[dict]:
        """解析 Markdown 表格为字典列表"""
        import re
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 过滤掉空行和分隔行（|---|---|）
        data_lines = [
            line for line in lines
            if line.strip() and not re.match(r'^\|[-| ]+\|$', line.strip())
        ]

        if len(data_lines) < 2:
            raise ValueError("表格至少需要表头和一行数据")

        # 解析表头
        headers = [h.strip() for h in data_lines[0].split("|") if h.strip()]

        # 解析数据行
        rows = []
        for line in data_lines[1:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))

        return rows

    async def remember(self, content, layer, category) -> MemoryWriteResult:
        """
        写入记忆（幂等）

        幂等性保证：
        1. 写入前检查相同 content + layer 是否已存在
        2. 已存在 → 更新 updated_at + access_count，不创建重复记录
        3. 不存在 → 新建

        返回：
        - created=True：新建
        - created=False：更新（重复写入）
        """
        # 幂等性检查：相同 content + layer 是否已存在
        existing = await self.storage.find_by_content(content, layer=layer)
        if existing:
            # 已存在 → 更新时间戳和访问计数
            existing.touch()  # 更新 updated_at
            await self.storage.update_access_count(existing.id, delta=1)
            logger.debug(f"幂等命中，更新已有记忆: {existing.id}")
            return MemoryWriteResult(
                id=existing.id,
                created=False,
                message="记忆已存在，已更新时间戳"
            )

        # 冲突检测
        similar = await self.storage.search(content, layer=layer, limit=5)
        conflicts = self.conflict_checker.check(content, similar)

        memory = Memory(
            content=content,
            layer=layer,
            category=category,
            conflicts=conflicts.conflict_ids,
        )
        result = await self.storage.upsert(memory)
        result.created = True
        return result

    async def build_context(self) -> AgentContext:
        """构建上下文"""
        hot = await self.storage.get_by_zone("hot", limit=20)
        standards = await self.storage.search("", layer="standard", limit=10)
        return AgentContext(
            personality=self.personality,
            hot_memories=hot,
            standards=standards,
        )

    async def decay_access_counts(self, factor: float = 0.9):
        """访问计数衰减"""
        await self.storage.decay_all_access_counts(factor)

    async def should_compress_cold_zone(self) -> bool:
        """检查是否需要冷区压缩"""
        cold_count = await self.storage.count(layer="core")
        return cold_count > 1000  # 超过 1000 条时触发

    async def compress_cold_zone(self):
        """冷区压缩"""
        cold = await self.storage.get_by_zone("cold", limit=100)
        # 压缩逻辑...

    # ---- pending_writes 重试机制 ----

    MAX_PENDING_RETRIES = 3

    async def flush_pending_writes(self):
        """
        启动时补写 pending_writes。

        重试机制：
        - 每条 pending_write 记录 retry_count
        - 重试超过 3 次 → 标记为 failed，不再重试
        - 记录到日志，用户可通过 `agent pending` 命令查看
        """
        pending = self._load_pending_writes()
        if not pending:
            return

        logger.info(f"开始补写 {len(pending)} 条 pending_writes")
        still_pending = []

        for item in pending:
            if item.get("retry_count", 0) >= self.MAX_PENDING_RETRIES:
                logger.error(
                    f"pending_write 重试超过 {self.MAX_PENDING_RETRIES} 次，"
                    f"标记为 failed: {item.get('id', 'unknown')}"
                )
                self._record_failed_write(item)
                continue

            try:
                await self.storage.upsert(Memory(**item["memory"]))
                logger.info(f"pending_write 补写成功: {item.get('id', 'unknown')}")
            except Exception as e:
                item["retry_count"] = item.get("retry_count", 0) + 1
                item["last_error"] = str(e)
                still_pending.append(item)
                logger.warning(
                    f"pending_write 补写失败（第 {item['retry_count']} 次）: {e}"
                )

        self._save_pending_writes(still_pending)
        if still_pending:
            logger.warning(f"仍有 {len(still_pending)} 条 pending_writes 未写入")

    def _load_pending_writes(self) -> list[dict]:
        """从文件加载 pending_writes"""
        path = self.data_dir / "pending_writes.json"
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            return []

    def _save_pending_writes(self, pending: list[dict]):
        """持久化 pending_writes"""
        path = self.data_dir / "pending_writes.json"
        if pending:
            with open(path, "w") as f:
                json.dump(pending, f, ensure_ascii=False, indent=2)
        elif path.exists():
            path.unlink()

    def _record_failed_write(self, item: dict):
        """记录最终失败的写入"""
        path = self.data_dir / "failed_writes.jsonl"
        item["failed_at"] = datetime.now().isoformat()
        with open(path, "a") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def backup(self, keep: int = 3):
        """数据备份"""
        self.storage.backup(keep=keep)

    def close(self):
        self.storage.close()
```

---

## 十、审计日志系统

> **安全开发专项要求：** 谁在什么时候写入了什么记忆、修改了什么配置，必须有完整记录。

### 9.1 审计日志设计

```python
# src/audit/logger.py

import json
import logging
from datetime import datetime
from pathlib import Path
from enum import Enum

class AuditAction(Enum):
    """审计操作类型"""
    MEMORY_WRITE = "memory_write"
    MEMORY_UPDATE = "memory_update"      # 幂等命中时的更新
    MEMORY_DELETE = "memory_delete"
    MEMORY_SEARCH = "memory_search"
    PERSONALITY_UPDATE = "personality_update"
    CONFIG_CHANGE = "config_change"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    LOGIN = "login"                      # CLI 启动
    LOGOUT = "logout"                    # CLI 关闭
    PENDING_WRITE_RETRY = "pending_write_retry"
    PENDING_WRITE_FAILED = "pending_write_failed"


class AuditLogger:
    """
    审计日志器

    记录所有关键操作的"谁、什么时候、做了什么、结果如何"。
    审计日志独立于应用日志，单独文件存储，不轮转（永久保留）。
    """

    def __init__(self, audit_log_path: str = "data/audit.jsonl"):
        self.audit_log_path = Path(audit_log_path)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, action: AuditAction, details: dict,
            success: bool = True, error: str = None):
        """
        记录一条审计日志

        Args:
            action: 操作类型
            details: 操作详情（如 memory_id, layer, content 摘要等）
            success: 是否成功
            error: 错误信息（失败时）
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "action": action.value,
            "success": success,
            "details": details,
        }
        if error:
            entry["error"] = error

        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def query(self, action: AuditAction = None,
              since: str = None, limit: int = 100) -> list[dict]:
        """
        查询审计日志

        Args:
            action: 按操作类型过滤
            since: ISO 时间字符串，只返回此时间之后的记录
            limit: 最多返回条数
        """
        results = []
        if not self.audit_log_path.exists():
            return results

        with open(self.audit_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if action and entry.get("action") != action.value:
                    continue
                if since and entry.get("timestamp", "") < since:
                    continue

                results.append(entry)
                if len(results) >= limit:
                    break

        return results
```

### 9.2 审计日志集成到记忆系统

```python
# src/memory/manager.py — 在 MemoryManager 中集成审计日志

class MemoryManager:
    def __init__(self, storage: MemoryStorage, data_dir: str,
                 audit_logger: AuditLogger = None):
        self.storage = storage
        self.data_dir = Path(data_dir)
        self.personality = self._load_personality()
        self.standards = self._load_standards()
        self.audit = audit_logger or AuditLogger(
            str(Path(data_dir) / "audit.jsonl")
        )

    async def remember(self, content, layer, category) -> MemoryWriteResult:
        """写入记忆（幂等 + 审计 + 只读检查）"""
        # 只读模式：拒绝所有写入
        if getattr(self, '_read_only', False):
            logger.warning(f"只读模式：拒绝写入记忆 [{layer}] {content[:50]}")
            self.audit.log(
                AuditAction.MEMORY_WRITE,
                details={"layer": layer, "content_preview": content[:50],
                         "reason": "read_only_rejected"},
                success=False, error="只读模式：写入被拒绝"
            )
            return MemoryWriteResult(id="", created=False,
                                     message="只读模式：写入被拒绝")

        existing = await self.storage.find_by_content(content, layer=layer)
        if existing:
            existing.touch()
            await self.storage.update_access_count(existing.id, delta=1)
            # 审计：幂等命中
            self.audit.log(
                AuditAction.MEMORY_UPDATE,
                details={
                    "memory_id": existing.id,
                    "layer": layer,
                    "reason": "idempotent_hit",
                    "content_preview": content[:50],
                }
            )
            return MemoryWriteResult(id=existing.id, created=False)

        similar = await self.storage.search(content, layer=layer, limit=5)
        conflicts = self.conflict_checker.check(content, similar)
        memory = Memory(content=content, layer=layer, category=category,
                        conflicts=conflicts.conflict_ids)
        result = await self.storage.upsert(memory)

        # 审计：新建记忆
        self.audit.log(
            AuditAction.MEMORY_WRITE,
            details={
                "memory_id": result.id,
                "layer": layer,
                "category": category,
                "content_preview": content[:100],
                "conflicts": conflicts.conflict_ids,
            }
        )
        result.created = True
        return result

    async def flush_pending_writes(self):
        """启动时补写 + 审计"""
        pending = self._load_pending_writes()
        if not pending:
            return

        self.audit.log(
            AuditAction.PENDING_WRITE_RETRY,
            details={"count": len(pending)}
        )
        # ... 原有重试逻辑 ...

        for item in pending:
            if item.get("retry_count", 0) >= self.MAX_PENDING_RETRIES:
                # 审计：pending 写入最终失败
                self.audit.log(
                    AuditAction.PENDING_WRITE_FAILED,
                    details={
                        "memory_id": item.get("id", "unknown"),
                        "retry_count": item["retry_count"],
                        "last_error": item.get("last_error", ""),
                    },
                    success=False,
                    error=item.get("last_error", "max retries exceeded")
                )
                # ...
```

### 9.3 审计日志 CLI 命令

```python
# src/entry/cli.py

@audit_app.command("show")
def audit_show(
    action: str = typer.Option(None, "--action", "-a", help="按操作类型过滤"),
    limit: int = typer.Option(20, "--limit", "-n", help="显示条数"),
    since: str = typer.Option(None, "--since", help="起始时间 ISO 格式"),
):
    """查看审计日志"""
    from src.audit.logger import AuditAction

    agent = get_current_agent()
    action_enum = AuditAction(action) if action else None
    entries = agent.memory.audit.query(
        action=action_enum, since=since, limit=limit
    )

    if not entries:
        typer.echo("暂无审计记录。")
        return

    for entry in entries:
        status = "✅" if entry["success"] else "❌"
        ts = entry["timestamp"][:19]
        typer.echo(
            f"{status} {ts} | {entry['action']:20s} | "
            f"{json.dumps(entry['details'], ensure_ascii=False)}"
        )
```

---

## 十一、CI 多环境验证（红线 14）

> **红线 14：没有测试不能合并。** CI 必须在多个 Python 版本和操作系统上验证。

### 10.1 GitHub Actions 配置

```yaml
# .github/workflows/ci.yml

name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
        os: [ubuntu-latest, macos-latest, windows-latest]
      fail-fast: false

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Lint
        run: |
          ruff check src/ tests/
          ruff format --check src/ tests/

      - name: Type check
        run: mypy src/ --strict

      - name: Unit tests
        run: pytest tests/unit/ -v --cov=src --cov-report=term-missing

      - name: Integration tests
        run: pytest tests/integration/ -v
        env:
          OPENAI_API_KEY: "sk-test-mock-key-for-ci"

  # 只有 main 分支才跑全量测试
  test-full:
    if: github.ref == 'refs/heads/main'
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -v --cov=src --cov-report=term-missing
```

### 10.2 CI 验证矩阵

| Python | Ubuntu | macOS | Windows |
|--------|--------|-------|---------|
| 3.12   | ✅      | ✅     | ✅       |
| 3.13   | ✅      | ✅     | ✅       |

> ℹ️ **平台说明**：V1 全平台支持（Linux/macOS/Windows）。文件权限通过 `_set_file_permission()` 跨平台封装：Linux/macOS 用 `os.chmod(0o600)`，Windows 用 `icacls` 命令。

---

## 十二、配置系统

> 设计来源：自主设计 — Pydantic Settings 类型验证 + 环境变量覆盖 + .env 支持

### 11.1 配置结构

```python
# src/config/settings.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

class Settings(BaseSettings):
    """
    应用配置

    加载优先级（高→低）：环境变量 > .env > config.yaml > 默认值
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LONG_AGENT_",
    )

    # === LLM ===
    llm_provider: str = Field(default="openai")
    openai_api_key: str = Field(...)
    openai_model: str = Field(default="gpt-4o")
    llm_timeout: int = Field(default=30, ge=5, le=120)
    llm_max_retries: int = Field(default=3, ge=0, le=10)

    # === 数据库 ===
    database_path: str = Field(default="data/memory.db")

    # === 数据 ===
    data_dir: str = Field(default="data")
    backup_dir: str = Field(default="data/backups")
    backup_keep: int = Field(default=3, ge=1, le=10)

    # === 日志 ===
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/agent.log")

    # === 上下文 ===
    context_max_messages: int = Field(default=20, ge=5, le=100)
    context_max_tokens: int = Field(default=100000, ge=10000, le=200000)
    context_protect_first: int = Field(default=3, ge=1, le=10)
    context_protect_last: int = Field(default=6, ge=1, le=20)

    # === 后台任务 ===
    backup_interval_hours: int = Field(default=24, ge=1, le=168)
    snapshot_cleanup_days: int = Field(default=7, ge=1)
    vacuum_interval_days: int = Field(default=30, ge=1)

    @field_validator("openai_api_key")
    @classmethod
    def validate_api_key(cls, v):
        if not v or not v.startswith("sk-"):
            raise ValueError("OPENAI_API_KEY 格式无效，应以 sk- 开头")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level 必须是 {allowed} 之一")
        return v.upper()
```

---

## 十三、可观测性设计

### 10.1 V1 边界声明

> **修复问题**：明确 V1 的边界，V2 再集成 Prometheus + Grafana。

```
┌─────────────────────────────────────────────────────────────┐
│                    可观测性 V1 边界                           │
│                                                              │
│  V1 做：                                                     │
│  ✅ 结构化 JSON 日志（logging + extra 参数）                 │
│  ✅ 关键指标采集（perf_counter 装饰器 + 日志写入）           │
│  ✅ LLM 延迟 / 记忆检索延迟 / 主循环耗时                     │
│                                                              │
│  V1 不做：                                                   │
│  ❌ Prometheus 指标导出                                      │
│  ❌ Grafana 仪表板                                           │
│  ❌ 自动告警                                                 │
│  ❌ 分布式追踪                                               │
│                                                              │
│  V2 计划：                                                   │
│  → 集成 Prometheus + Grafana                                 │
│  → P95/P99 聚合（通过 Prometheus histogram）                │
│  → 告警规则：LLM 错误率 > 5% / 主循环耗时 P95 > 10s         │
│  → OpenTelemetry 追踪                                       │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 指标采集

```python
# src/observability/metrics.py

import time
import logging

logger = logging.getLogger("long_agent.metrics")

class MetricsCollector:
    """指标采集器 — V1（日志记录，V2 集成 Prometheus）"""

    @staticmethod
    def measure_llm_latency(func):
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                latency_ms = (time.perf_counter() - start) * 1000
                logger.info("llm_call", extra={
                    "event": "llm_call",
                    "latency_ms": round(latency_ms, 2),
                    "model": result.model,
                    "tokens_used": result.tokens_used,
                    "status": "success",
                })
                return result
            except Exception as e:
                latency_ms = (time.perf_counter() - start) * 1000
                logger.warning("llm_call_failed", extra={
                    "event": "llm_call_failed",
                    "latency_ms": round(latency_ms, 2),
                    "error": str(e),
                    "status": "failed",
                })
                raise
        return wrapper

    @staticmethod
    def log_compression_quality(original_count: int, compressed_count: int,
                                 quality: dict):
        """
        记录上下文压缩质量指标

        指标：
        - compression_ratio: 压缩率 = 1 - 压缩后/压缩前
        - info_retention: 信息保留率 = 摘要关键词覆盖原文关键词比例
        - quality_score: 质量分 = 保留率×0.7 + (1-压缩率)×0.3
        """
        logger.info("context_compression", extra={
            "event": "context_compression",
            "original_count": original_count,
            "compressed_count": compressed_count,
            "compression_ratio": round(
                1 - compressed_count / max(original_count, 1), 3
            ),
            "info_retention": round(quality.get("info_retention", 0), 3),
            "quality_score": round(quality.get("quality_score", 0), 3),
        })
```

### 10.3 关键指标

| 指标 | 目标 | V1 采集方式 | V2 聚合方式 |
|------|------|------------|------------|
| LLM 调用延迟 | P95 < 5s | perf_counter → 日志 | Prometheus histogram |
| 记忆检索延迟 | P95 < 100ms | perf_counter → 日志 | Prometheus histogram |
| 主循环总耗时 | P95 < 10s | perf_counter → 日志 | Prometheus histogram |
| 上下文压缩比 | 30%-70% | 压缩前后消息数 → 日志 | Prometheus histogram |
| 信息保留率 | > 60% | 关键词覆盖率 → 日志 | Prometheus histogram |
| 压缩质量分 | > 0.5 | 保留率×0.7 + (1-压缩率)×0.3 → 日志 | Prometheus histogram |
| LLM 错误率 | < 5% | 日志统计 | Prometheus counter + 告警 |

---

## 十四、测试策略

### 11.1 测试框架（对齐 ADR-001 决策 6）

| 组件 | 选型 |
|------|------|
| pytest | 测试框架 |
| pytest-asyncio | 异步测试支持 |
| pytest-mock | Mock LLM 调用 |
| pytest-cov | 覆盖率统计 |

### 11.2 LLM 相关代码测试方案

> **修复问题**：明确各种 LLM 相关场景的 mock 策略。

```python
# tests/conftest.py

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# === 1. Mock LLM 基础返回 ===

@pytest.fixture
def mock_llm():
    """Mock LLM 客户端"""
    with patch("src.loop.agent_loop.LLMProviderFactory") as mock_factory:
        instance = mock_factory.create.return_value
        instance.spec = get_model_spec("gpt-4o")

        # 非流式调用
        instance.chat = AsyncMock(return_value=LLMResponse(
            content='{"type": "memory_write", "confidence": 0.92}',
            tokens_used=100, model="gpt-4o", latency_ms=500,
        ))

        # 流式调用
        async def mock_stream(*args, **kwargs):
            for chunk in ["好的", "，", "已", "记住"]:
                yield chunk
        instance.stream = mock_stream

        # Token 计算
        instance.count_tokens = MagicMock(return_value=500)

        yield instance

# === 2. Mock 上下文压缩 ===

@pytest.fixture
def mock_compressor():
    """Mock 上下文压缩器"""
    with patch("src.understanding.context_compressor.ContextCompressor") as mock:
        instance = mock.return_value
        instance.compress = AsyncMock(side_effect=lambda msgs: msgs)  # 原样返回
        instance.should_compress = MagicMock(return_value=False)
        instance.count_tokens = MagicMock(return_value=50000)
        yield instance

# === 3. Mock 各种错误类型 ===

@pytest.fixture
def mock_llm_with_errors():
    """Mock LLM 返回各种错误（用于测试错误恢复）"""
    with patch("src.loop.agent_loop.LLMProviderFactory") as mock_factory:
        instance = mock_factory.create.return_value
        instance.spec = get_model_spec("gpt-4o")

        # 可配置：按顺序返回不同错误
        from openai import APIConnectionError, RateLimitError, AuthenticationError

        errors = [
            APIConnectionError(request=MagicMock()),  # 连接错误 → 重试
            RateLimitError(response=MagicMock(), body=None),  # 限流 → 等待重试
        ]
        instance.chat = AsyncMock(side_effect=errors)

        yield instance

# === 4. Mock 流式输出 ===

@pytest.fixture
def mock_stream_chunks():
    """Mock 流式输出的 chunks"""
    chunks = ["分析", "结果", "：", "1.", " ...", "2.", " ..."]
    async def mock_stream(*args, **kwargs):
        for chunk in chunks:
            yield chunk
    return mock_stream
```

### 11.3 LLM 测试场景清单

| 场景 | Mock 策略 | 测试目标 |
|------|----------|---------|
| 正常意图解析 | mock_llm 返回固定 JSON | 验证意图解析流程 |
| 上下文压缩 | mock_compressor 返回摘要消息 | 验证压缩触发和消息组装 |
| LLM 连接错误 | mock_llm_with_errors 抛 APIConnectionError | 验证重试 3 次 |
| LLM 限流错误 | mock_llm_with_errors 抛 RateLimitError | 验证等待 + 重试 |
| LLM 认证错误 | mock_llm_with_errors 抛 AuthenticationError | 验证立即停止 + 用户提示 |
| context_overflow | 错误消息含 "context length" | 验证压缩后重试 |
| 流式输出 | mock_stream_chunks | 验证 StreamPrinter 逐 token 打印 |
| 记忆写入失败 | mock storage.upsert 抛 DatabaseError | 验证入 pending_writes 队列 |

### 11.4 测试目录结构

```
tests/
├── conftest.py                  # 全局 fixture
├── unit/
│   ├── test_memory_manager.py
│   ├── test_personality_schema.py
│   ├── test_error_classifier.py
│   ├── test_context_compressor.py
│   ├── test_input_filter.py
│   ├── test_conflict_checker.py
│   └── test_model_registry.py   # 新增：模型注册表
├── integration/
│   ├── test_agent_loop.py       # 主循环端到端
│   ├── test_entry_system.py     # 入口系统
│   └── test_llm_provider.py     # LLM 提供商（mock）
└── fixtures/
    ├── personality_valid.md
    └── personality_invalid.md
```

### 11.5 测试覆盖率目标

| 模块 | 最低覆盖率 |
|------|-----------|
| 记忆系统 | > 95% |
| 错误分类 | > 95% |
| 上下文压缩 | > 90% |
| 理解层 | > 80% |
| 主循环 | > 85% |
| 整体 | > 85% |

---

## 十五、安全设计

### 12.1 安全分层

| 层级 | 功能 |
|------|------|
| 第1层 | 输入过滤（长度限制、注入检测） |
| 第2层 | 冲突检测（逻辑矛盾、否定对） |
| 第3层 | 错误分类（含 context_overflow 恢复） |
| 第4层 | 危险操作暂停（删除/清空/重置需确认） |
| 第5层 | 数据备份（每次关闭前 + 每日自动） |

### 12.2 危险操作定义

| 操作 | 级别 | 处理 |
|------|------|------|
| 写入记忆 | 🟡 低 | 冲突检测通过后执行 |
| 删除记忆 | 🟠 中 | 需用户确认 |
| 清空所有记忆 | 🔴 高 | 需用户确认 + 二次确认 |
| 重置人格 | 🟠 中 | 需用户确认 |
| 修改第3层标准 | 🟡 低 | 直接执行 |

---

## 十六、数据流向

### 13.1 模块间数据流（完整版）

```
                         用户输入
                            │
                            ▼
                   ┌────────────────┐
                   │   入口系统      │
                   │  CLI / 库      │
                   └───┬────────────┘
                       │
                       ▼
                   ┌────────────────┐
                   │  Agent 主循环   │
                   └───┬──┬──┬──┬──┘
                       │  │  │  │
          ┌────────────┘  │  │  └────────────────┐
          ▼               │  │                   ▼
   ┌─────────────┐        │  │           ┌──────────────┐
   │   理解层     │        │  │           │   安全模块    │
   │             │        │  │           │              │
   │ parse() ──────────► LLM 适配器      │ 冲突检测     │
   │ compress() ◄──────── │  │           │ 错误分类     │
   │             │        │  │           │ 输入过滤     │
   └─────────────┘        │  │           └──────┬───────┘
                          │  │                  │
                          ▼  ▼                  ▼
                   ┌──────────────────────────────────────┐
                   │      记忆系统（存储抽象层）            │
                   │                                      │
                   │  V1: SQLiteStorage                   │
                   │  V2: RedisStorage + SQLiteStorage    │
                   │                                      │
                   │  备份 ◄── 后台任务                    │
                   └──────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────┐
   │              后台任务                                 │
   │  对话后：访问计数衰减                                 │
   │  每日 3:00：冷区压缩 + 数据备份 + 快照清理          │
   └──────────────────────────────────────────────────────┘
```

---

## 十七、CLI 交互设计

### 14.1 交互模式

```
$ python -m long_agent

Long Agent v1.0
输入 "帮助" 查看命令，输入 "退出" 结束对话。

> 记住我喜欢简洁风格
Agent: 好的，已记住你喜欢简洁风格。（流式输出）

> 帮我分析这个项目的代码质量
Agent: （流式输出中...）

> 退出
Agent: 再见！
```

### 14.2 特殊命令

| 命令 | 功能 |
|------|------|
| `帮助` | 显示可用命令 |
| `停` | 停止当前操作 |
| `退出` | 结束对话 |
| `清空记忆` | 清空所有记忆（需确认 + 二次确认） |
| `重置人格` | 重置 HEXACO 到 50（需确认） |
| `查看记忆` | 显示记忆摘要 |
| `查看人格` | 显示 HEXACO 评分 |

---

## 十八、文件结构

```
long_agent/
├── pyproject.toml
├── config.yaml
├── .env
├── data/
│   ├── personality.md
│   ├── memory.db
│   ├── standards/
│   └── backups/                 # 数据备份目录
│       ├── memory_20260501_030000.db
│       ├── memory_20260502_030000.db
│       └── memory_20260503_030000.db
├── logs/
│   └── agent.log
├── migrations/
│   └── 001_initial.sql
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── entry/
│   │   ├── cli.py                # CLI 入口（统一 event loop）
│   │   ├── library.py            # 库入口
│   │   └── signals.py            # 优雅关闭
│   ├── config/
│   │   └── settings.py           # Pydantic Settings
│   ├── loop/
│   │   └── agent_loop.py         # AgentLoop
│   ├── memory/
│   │   ├── manager.py            # MemoryManager
│   │   ├── storage/
│   │   │   ├── base.py           # MemoryStorage 抽象接口
│   │   │   └── sqlite_storage.py # SQLite 实现
│   │   ├── migration.py
│   │   └── personality_schema.py
│   ├── understanding/
│   │   ├── intent.py
│   │   └── context_compressor.py # tiktoken 精确计算
│   ├── security/
│   │   ├── conflict.py
│   │   ├── filter.py
│   │   ├── approval.py
│   │   └── errors/
│   │       └── classifier.py     # 含 context_overflow
│   ├── llm/
│   │   ├── base.py               # LLMProvider 抽象
│   │   ├── model_registry.py     # 模型注册表
│   │   ├── openai_provider.py    # OpenAI 实现
│   │   └── factory.py
│   ├── background/
│   │   └── manager.py            # 对话后触发 + 每日定时
│   ├── output/
│   │   └── stream_printer.py
│   └── observability/
│       └── metrics.py            # V1 边界声明
└── tests/
    ├── conftest.py               # 含 LLM mock 方案
    ├── unit/
    ├── integration/
    └── fixtures/
```

---

## 十九、变更记录

| 日期 | 版本 | 变更 | 操作人 |
|------|------|------|--------|
| 2026-05-01 | v1.0 | 初版创建 | 前台 |
| 2026-05-01 | v1.1 | 8 条改进：V1 执行范围、规划内联、跑偏降级、错误恢复、迁移策略、指标采集、Schema 校验、数据流补全 | 前台 |
| 2026-05-01 | v1.2 | 8 条改进：入口系统、上下文压缩、LLM 插件化、流式输出、后台任务、错误分类、测试策略、配置验证 | 前台 |
| 2026-05-01 | v1.3 | 9 条改进：模型注册表（不硬编码 max_context）、tiktoken 精确 token 计算、context_overflow 恢复流程、后台任务改为对话后触发+每日定时、LLM 测试方案、可观测性 V1 边界声明、数据备份、统一 event loop、存储抽象层 | 前台 |
| 2026-05-01 | v1.4 | 审查修复：状态机（AgentState 枚举 + 合法转换表 + StateMachine 类）、幂等性（remember 精确匹配 + find_by_content）、审计日志（AuditLogger + CLI audit show）、personality.md 防御性降级（校验失败→默认人格）、统一错误处理策略（三类错误三种处理方式）、只读模式（--read-only CLI + LongAgent.read_only + 写入拦截）、pending_writes 去重、BatchWriteResult 数据结构、log_compression_quality 压缩质量指标、personality.md Schema 校验 | 前台 |
| 2026-05-01 | v1.5 | 审查修复：补充 CI 多环境验证矩阵（Python 3.12/3.13 × Ubuntu/macOS/Windows）、章节编号整理（一至十九连续无重复） | 前台 |
| 2026-05-01 | v1.6 | 完整 Windows 支持：CHARTER.md 移除"不支持 Windows"改为"跨平台文件权限"、SQLiteStorage 新增 _set_file_permission() 跨平台方法（Linux/macOS chmod / Windows icacls）、失败时 warning 日志替代静默 pass | 前台 |
