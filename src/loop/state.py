"""
状态机 — Agent 生命周期管理

11 状态版本（对齐 DESIGN.md 三、Agent 状态机设计）

状态流：
IDLE → PERCEIVING → UNDERSTANDING → PLANNING → EXECUTING → OBSERVING → REFLECTING → REPLYING → IDLE
              │              │              │            │            │
              ↓              ↓              ↓            ↓            ↓
           FAILED       CLARIFYING    WAITING_APPROVAL  FAILED    EXECUTING(重试)
              │              │              │                         │
              ↓              ↓              ↓                         ↓
           IDLE         UNDERSTANDING   EXECUTING/IDLE            FAILED

V2 升级（合并自 hermse v1.3）：
- 自适应超时：每个状态的超时时间根据其特性动态计算
  - IDLE: 无超时
  - PERCEIVING/UNDERSTING: timeout = estimated_steps * avg_step_time * 1.5
  - EXECUTING: timeout = estimated_steps * avg_step_time * 1.5
  - WAITING_APPROVAL: timeout = tool_timeout * 2
  - CLARIFYING: timeout = user_defined or 3600s
- 心跳检测：自适应间隔 min(32, max(3, state_timeout // 10))
- 消息队列：可中断状态立即处理，不可中断状态排队（优先级堆）
- 重试策略：基于失败原因自适应（工具失败:指数退避x3, LLM失败:切换模型x2, 状态损坏:快照恢复x1）

参考：06_状态机设计.md
"""

import heapq
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from src.errors.classifier import AdaptiveRetryPolicy

logger = logging.getLogger("long_agent.loop.state")


class AgentState(Enum):
    """Agent 状态枚举 — 11 状态"""

    IDLE = "idle"
    PERCEIVING = "perceiving"  # ①感知：读取上下文
    UNDERSTANDING = "understanding"  # ②理解：解析意图
    PLANNING = "planning"  # ③规划：确定操作
    EXECUTING = "executing"  # ④执行：执行操作
    OBSERVING = "observing"  # ⑤观察：检查结果
    REFLECTING = "reflecting"  # ⑥反思：更新记忆
    REPLYING = "replying"  # ⑦回复：返回结果
    WAITING_APPROVAL = "waiting_approval"  # 等待用户审批
    CLARIFYING = "clarifying"  # 追问澄清
    FAILED = "failed"  # 失败，需要恢复


class IllegalStateTransitionError(Exception):
    """非法状态转换错误"""

    def __init__(self, message: str):
        super().__init__(message)


# 合法状态转换表（对齐 DESIGN.md 3.2）
VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {
        AgentState.PERCEIVING,
    },
    AgentState.PERCEIVING: {
        AgentState.UNDERSTANDING,
        AgentState.FAILED,
    },
    AgentState.UNDERSTANDING: {
        AgentState.PLANNING,
        AgentState.CLARIFYING,
        AgentState.FAILED,
    },
    AgentState.CLARIFYING: {
        AgentState.UNDERSTANDING,
        AgentState.FAILED,
    },
    AgentState.PLANNING: {
        AgentState.EXECUTING,
        AgentState.WAITING_APPROVAL,
    },
    AgentState.WAITING_APPROVAL: {
        AgentState.EXECUTING,
        AgentState.IDLE,
    },
    AgentState.EXECUTING: {
        AgentState.OBSERVING,
        AgentState.FAILED,
    },
    AgentState.OBSERVING: {
        AgentState.REFLECTING,
        AgentState.EXECUTING,  # 跑偏重试
        AgentState.FAILED,
    },
    AgentState.REFLECTING: {
        AgentState.REPLYING,
    },
    AgentState.REPLYING: {
        AgentState.IDLE,
    },
    AgentState.FAILED: {
        AgentState.IDLE,
        AgentState.REFLECTING,
    },
}


class StateMachine:
    """
    Agent 状态机 — 强制合法转换 + 进入/退出动作（对齐 DESIGN.md 3.3 / DESIGN-V2 §5）

    非法转换直接拒绝，不静默忽略。
    每次转换自动执行：退出旧状态动作 → 转换 → 进入新状态动作。
    """

    def __init__(self, initial: AgentState = AgentState.IDLE):
        self._state = initial
        self._history: list[tuple[str, str, str]] = []  # (from, to, timestamp)
        self._timeout_mgr = AdaptiveTimeoutManager()
        self._retry_policy = AdaptiveRetryPolicy()
        self._state_entry_time: dict[str, float] = {}
        logger.info(f"状态机初始化：{initial.value}")

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def history(self) -> list[tuple[str, str, str]]:
        return list(self._history)

    @property
    def timeout_manager(self) -> "AdaptiveTimeoutManager":
        return self._timeout_mgr

    @property
    def retry_policy(self) -> "AdaptiveRetryPolicy":
        return self._retry_policy

    def can_transition_to(self, new_state: AgentState) -> bool:
        """检查是否可以转换到目标状态"""
        return new_state in VALID_TRANSITIONS.get(self._state, set())

    def transition_to(self, new_state: AgentState) -> None:
        """
        执行状态转换（含进入/退出动作）

        流程：
        1. 校验合法性
        2. 执行旧状态退出动作（清理、记录耗时）
        3. 执行转换（记录历史）
        4. 执行新状态进入动作（初始化、启动超时计时）

        非法转换直接 raise IllegalStateTransitionError，不静默忽略。
        """
        if not self.can_transition_to(new_state):
            allowed = VALID_TRANSITIONS.get(self._state, set())
            raise IllegalStateTransitionError(
                f"非法状态转换：{self._state.value} → {new_state.value}。"
                f"允许的目标：{[s.value for s in allowed]}"
            )

        old_state = self._state

        # 2. 退出旧状态动作
        self._on_exit_state(old_state)

        # 3. 执行转换
        self._state = new_state

        from datetime import datetime

        ts = datetime.utcnow().isoformat() + "Z"
        self._history.append((old_state.value, new_state.value, ts))

        # 4. 进入新状态动作
        self._on_enter_state(new_state)

        logger.info(f"状态转换：{old_state.value} → {new_state.value}")

    def _on_exit_state(self, state: AgentState):
        """
        退出状态动作：
        - 记录实际耗时（用于自适应超时学习）
        - FAILED: 记录失败信息
        - EXECUTING: 保存快照标记
        """
        import time as _time

        now = _time.time()
        state_key = state.value

        if state_key in self._state_entry_time:
            elapsed = int(now - self._state_entry_time[state_key])
            self._timeout_mgr.record_actual_timeout(state, elapsed)
            del self._state_entry_time[state_key]

        if state == AgentState.FAILED:
            logger.warning("退出 FAILED 状态，准备恢复或重置")

    def _on_enter_state(self, state: AgentState):
        """
        进入状态动作：
        - 记录进入时间（用于超时检测）
        - IDLE: 清理历史（保留最近100条）
        - WAITING_APPROVAL: 启动超时计时
        - CLARIFYING: 启动超时计时
        - FAILED: 触发恢复策略
        """
        import time as _time

        self._state_entry_time[state.value] = _time.time()

        if state == AgentState.IDLE:
            # 保留最近100条历史
            if len(self._history) > 100:
                self._history = self._history[-100:]
            logger.debug("进入 IDLE：历史记录已裁剪")

        elif state == AgentState.WAITING_APPROVAL:
            timeout = self._timeout_mgr.get_timeout(state)
            logger.info(f"进入 WAITING_APPROVAL：超时 {timeout}s")

        elif state == AgentState.CLARIFYING:
            timeout = self._timeout_mgr.get_timeout(state)
            logger.info(f"进入 CLARIFYING：超时 {timeout}s")

        elif state == AgentState.FAILED:
            logger.warning("进入 FAILED 状态，等待恢复策略决策")

    def reset(self):
        """重置到 IDLE"""
        self._state = AgentState.IDLE
        self._history.clear()
        self._state_entry_time.clear()
        logger.info("状态机重置为 IDLE")

    def get_heartbeat_interval(self) -> int:
        """获取当前状态的自适应心跳间隔"""
        return self._timeout_mgr.get_heartbeat_interval(self._state)

    def get_current_timeout(self) -> Optional[int]:
        """获取当前状态的超时时间"""
        return self._timeout_mgr.get_timeout(self._state)

    def get_retry_policy(self, failure_reason: str) -> dict:
        """获取自适应重试策略"""
        return self._retry_policy.get_retry_policy(failure_reason)

    def __repr__(self):
        return f"StateMachine(state={self._state.value})"


# ========== V2 升级：自适应超时 + 心跳 + 消息队列 + 自适应重试 ==========


@dataclass
class StateTimeoutConfig:
    """状态超时配置（自适应）"""

    state: AgentState
    timeout_seconds: Optional[int] = None  # None = 无超时
    heartbeat_interval: int = 30  # 心跳间隔（秒）
    user_defined_timeout: Optional[int] = None  # 用户定义的超时


class AdaptiveTimeoutManager:
    """
    自适应超时管理器（合并自 hermse v1.3）

    每个状态的超时时间根据其特性动态计算，不写死固定值。
    超时来源：用户历史数据拟合或 LLM 动态评估。
    """

    # 超时配置来源：动态计算，仅首次使用的初始值
    # 运行后根据用户行为数据持续自适应
    _DEFAULT_PAUSED_TIMEOUT = 3600  # PAUSED 默认超时 3600 秒（仅初始值）

    def __init__(self):
        self._timeout_history: dict[str, list[int]] = {}
        self._response_time_history: dict[str, list[float]] = {}

    def get_timeout(self, state: AgentState, context: dict = None) -> Optional[int]:
        """
        获取指定状态的自适应超时时间（秒）。

        科学依据：不同状态的不确定性来源不同，超时策略应匹配其特性。
        - IDLE: 无外部依赖，不需要超时
        - PERCEIVING/UNDERSTANDING: 超时取决于模型推理时间
        - EXECUTING: 超时取决于任务复杂度（步骤数 × 单步耗时）
        - WAITING_APPROVAL: 超时取决于用户历史响应时间
        - CLARIFYING: 超时由用户决定，默认3600s防止永久挂起
        """
        context = context or {}

        if state == AgentState.IDLE:
            return None

        # 从历史数据学习超时（替代写死值）
        if state.value in self._timeout_history and self._timeout_history[state.value]:
            import statistics

            return int(statistics.median(self._timeout_history[state.value]))

        # 无历史数据时的启发式计算（仅首次）
        if state in (AgentState.PERCEIVING, AgentState.UNDERSTANDING, AgentState.EXECUTING):
            estimated_steps = context.get("estimated_steps", 20)
            avg_step_time = context.get("avg_step_time", 60)
            return int(estimated_steps * avg_step_time * 1.5)

        if state == AgentState.WAITING_APPROVAL:
            # 从用户历史响应时间学习
            if "user_response_time" in context:
                return int(context["user_response_time"] * 2)
            tool_timeout = context.get("tool_timeout", 300)
            return int(tool_timeout * 2)

        if state == AgentState.CLARIFYING:
            return context.get("user_defined_timeout", self._DEFAULT_PAUSED_TIMEOUT)

        return None

    def get_heartbeat_interval(self, state: AgentState, context: dict = None) -> int:
        """
        获取自适应心跳检测间隔（秒）。

        科学依据：心跳频率应与超时时间成反比。
        - 超时短 → 心跳频繁（防止错过超时窗口）
        - 超时长 → 心跳稀疏（减少资源消耗）
        - 上限32秒，下限3秒
        - IDLE 状态心跳间隔为60秒（仅需检测存活）
        """
        if state == AgentState.IDLE:
            return 60

        timeout = self.get_timeout(state, context)
        if timeout is None:
            return 60
        return min(32, max(3, timeout // 10))

    def record_actual_timeout(self, state: AgentState, actual_seconds: int):
        """记录实际超时数据，用于在线学习"""
        if state.value not in self._timeout_history:
            self._timeout_history[state.value] = []
        self._timeout_history[state.value].append(actual_seconds)
        # 保留最近100条
        if len(self._timeout_history[state.value]) > 100:
            self._timeout_history[state.value] = self._timeout_history[state.value][-100:]


@dataclass(order=True)
class PrioritizedMessage:
    """带优先级的消息（用于消息队列）"""

    priority: int
    timestamp: float
    message: Any = field(compare=False)
    msg_type: str = field(compare=False)  # "interrupt" / "normal"


class MessagePriority:
    """消息优先级定义"""

    EMERGENCY = 0  # 紧急：系统关闭、强制停止
    CONTROL = 1  # 控制：pause, cancel, resume
    APPROVAL = 2  # 审批：approval_granted, approval_denied
    NORMAL = 3  # 普通：新任务、查询


class MessageQueue:
    """
    Agent 消息队列（合并自 hermse v1.3）

    设计原则：
    - 可中断状态的消息立即处理（不进入队列）
    - 不可中断状态的消息按优先级排队
    - 同优先级按时间顺序处理（FIFO）
    """

    # 各状态下允许立即处理的触发器
    INTERRUPTIBLE_TRIGGERS = {
        AgentState.IDLE: "*",
        AgentState.PERCEIVING: "*",
        AgentState.UNDERSTANDING: "*",
        AgentState.PLANNING: "*",
        AgentState.EXECUTING: {"pause", "cancel", "interrupt"},
        AgentState.OBSERVING: "*",
        AgentState.REFLECTING: "*",
        AgentState.REPLYING: "*",
        AgentState.WAITING_APPROVAL: {"approval_granted", "approval_denied", "timeout"},
        AgentState.CLARIFYING: "*",
        AgentState.FAILED: "*",
    }

    def __init__(self, state_machine: StateMachine):
        self._queue = []
        self._lock = threading.Lock()
        self._state_machine = state_machine

    def is_interruptible(self, trigger: str) -> bool:
        """检查当前状态下该触发器是否可立即处理"""
        current = self._state_machine.state
        allowed = self.INTERRUPTIBLE_TRIGGERS.get(current, set())
        if allowed == "*":
            return True
        return trigger in allowed

    def enqueue(
        self, trigger: str, priority: int = MessagePriority.NORMAL, metadata: dict = None
    ) -> bool:
        """处理消息：可中断则立即处理，否则入队排队"""
        if self.is_interruptible(trigger):
            return True  # 立即处理由调用方执行
        with self._lock:
            heapq.heappush(
                self._queue,
                PrioritizedMessage(
                    priority=priority,
                    timestamp=time.time(),
                    message={"trigger": trigger, "metadata": metadata},
                    msg_type="normal",
                ),
            )
        return True

    def process_queue(self):
        """处理队列中的消息"""
        with self._lock:
            while self._queue:
                item = heapq.heappop(self._queue)
                trigger = item.message["trigger"]
                if self.is_interruptible(trigger):
                    pass  # 由状态机执行转换
                else:
                    heapq.heappush(self._queue, item)
                    break


# ========== V2 AgentStateMachine — 7 状态 + TransitionTrigger + StatePersistence ==========

import json
import os
import sqlite3


class TransitionTrigger(Enum):
    """状态转换触发器（V2）"""

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


@dataclass
class StateTransition:
    """状态转换记录"""

    from_state: str = ""
    to_state: str = ""
    trigger: str = ""
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@dataclass
class StateSnapshot:
    """状态快照"""

    agent_id: str = ""
    task_id: str = ""
    state: str = ""
    metadata: dict = field(default_factory=dict)
    timeout_config: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class AgentStateMachine:
    """
    Agent 状态机（V2）— 有限状态机（FSM）

    7 状态：IDLE → READY → EXECUTING → PAUSED / WAITING / COMPLETED / FAILED

    设计原则：
    1. 状态转换必须显式声明
    2. 每个状态有明确的进入/退出动作
    3. 非法转换必须拒绝
    4. 状态持久化（支持恢复）
    5. 所有超时参数由公式/LLM/用户互动获得，不写死
    """

    def __init__(self):
        self._transitions = {
            ("IDLE", TransitionTrigger.TASK_RECEIVED): "READY",
            ("READY", TransitionTrigger.START_EXECUTION): "EXECUTING",
            ("READY", TransitionTrigger.CANCEL): "IDLE",
            ("EXECUTING", TransitionTrigger.PAUSE): "PAUSED",
            ("EXECUTING", TransitionTrigger.NEED_APPROVAL): "WAITING",
            ("EXECUTING", TransitionTrigger.COMPLETE): "COMPLETED",
            ("EXECUTING", TransitionTrigger.FAIL): "FAILED",
            ("PAUSED", TransitionTrigger.RESUME): "EXECUTING",
            ("PAUSED", TransitionTrigger.CANCEL): "IDLE",
            ("WAITING", TransitionTrigger.APPROVAL_GRANTED): "EXECUTING",
            ("WAITING", TransitionTrigger.APPROVAL_DENIED): "FAILED",
            ("WAITING", TransitionTrigger.APPROVAL_TIMEOUT): "IDLE",
            ("COMPLETED", TransitionTrigger.NEW_TASK): "IDLE",
            ("FAILED", TransitionTrigger.RETRY): "EXECUTING",
            ("FAILED", TransitionTrigger.CANCEL): "IDLE",
        }
        self._entry_actions = {
            "READY": self._on_enter_ready,
            "EXECUTING": self._on_enter_executing,
            "PAUSED": self._on_enter_paused,
            "WAITING": self._on_enter_waiting,
            "COMPLETED": self._on_enter_completed,
            "FAILED": self._on_enter_failed,
        }
        self._exit_actions = {
            "EXECUTING": self._on_exit_executing,
            "PAUSED": self._on_exit_paused,
            "WAITING": self._on_exit_waiting,
        }
        self._current_state = "IDLE"
        self._transition_history: list[StateTransition] = []
        logger.info("AgentStateMachine V2 初始化完成")

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def history(self) -> list[StateTransition]:
        return list(self._transition_history)

    def can_transition(self, trigger: TransitionTrigger) -> bool:
        """检查是否可以执行某个转换"""
        return (self._current_state, trigger) in self._transitions

    def transition(self, trigger: TransitionTrigger, metadata: dict = None) -> bool:
        """
        执行状态转换

        Returns:
            bool: 转换是否成功
        """
        key = (self._current_state, trigger)
        if key not in self._transitions:
            logger.warning(f"非法状态转换: {self._current_state} + {trigger.value}")
            return False

        target_state = self._transitions[key]

        # 执行退出动作
        if self._current_state in self._exit_actions:
            self._exit_actions[self._current_state]()

        # 更新状态
        old_state = self._current_state
        self._current_state = target_state

        # 记录历史
        self._transition_history.append(
            StateTransition(
                from_state=old_state,
                to_state=target_state,
                trigger=trigger.value,
                metadata=metadata or {},
            )
        )

        # 执行进入动作
        if target_state in self._entry_actions:
            self._entry_actions[target_state]()

        logger.info(f"状态转换: {old_state} → {target_state} ({trigger.value})")
        return True

    # === 进入动作 ===
    def _on_enter_ready(self):
        logger.info("进入 READY：等待执行")

    def _on_enter_executing(self):
        logger.info("进入 EXECUTING：开始执行")

    def _on_enter_paused(self):
        logger.info("进入 PAUSED：已暂停")

    def _on_enter_waiting(self):
        logger.info("进入 WAITING：等待审批")

    def _on_enter_completed(self):
        logger.info("进入 COMPLETED：执行完成")

    def _on_enter_failed(self):
        logger.warning("进入 FAILED：执行失败")

    # === 退出动作 ===
    def _on_exit_executing(self):
        logger.info("退出 EXECUTING：执行结束")

    def _on_exit_paused(self):
        logger.info("退出 PAUSED：恢复或取消")

    def _on_exit_waiting(self):
        logger.info("退出 WAITING：审批结果已出")


class StatePersistence:
    """
    状态持久化 — SQLite + JSON 双格式

    SQLite 用于需要查询、索引和事务安全的场景。
    JSON 用于轻量级场景（备份、导出）。

    设计文档：DESIGN-V2.md §9.4
    """

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: SQLite 数据库路径（None 时由用户配置或 LLM 动态确定）
        """
        self.db_path = db_path or "./data/agent_state.db"
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    task_id TEXT,
                    state TEXT NOT NULL,
                    metadata TEXT,
                    timeout_config TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS heartbeats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    task_id TEXT,
                    state TEXT NOT NULL,
                    interval INTEGER,
                    timeout INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
        logger.info(f"StatePersistence 初始化完成: {self.db_path}")

    def save_snapshot(self, snapshot: StateSnapshot, agent_id: str, timeout_config: dict):
        """
        保存状态快照

        Args:
            snapshot: 状态快照
            agent_id: Agent ID
            timeout_config: 超时配置
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO state_snapshots
                   (agent_id, task_id, state, metadata, timeout_config, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    agent_id,
                    snapshot.task_id,
                    snapshot.state,
                    json.dumps(snapshot.metadata),
                    json.dumps(timeout_config),
                    snapshot.timestamp,
                ),
            )
            conn.commit()
        logger.debug(f"快照保存: agent={agent_id}, state={snapshot.state}")

    def load_latest_snapshot(self, task_id: str) -> Optional[dict]:
        """
        加载最新的状态快照

        Args:
            task_id: 任务 ID

        Returns:
            dict or None: 最新快照
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT * FROM state_snapshots
                   WHERE task_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
        if row:
            return dict(row)
        return None

    def record_transition(self, transition: StateTransition, agent_id: str):
        """
        记录状态转换

        Args:
            transition: 状态转换记录
            agent_id: Agent ID
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO state_transitions
                   (agent_id, from_state, to_state, trigger, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    agent_id,
                    transition.from_state,
                    transition.to_state,
                    transition.trigger,
                    json.dumps(transition.metadata),
                    transition.timestamp,
                ),
            )
            conn.commit()
        logger.debug(f"转换记录: {transition.from_state} → {transition.to_state}")

    def record_heartbeat(
        self, agent_id: str, task_id: str, state: str, interval: int, timeout: int = None
    ):
        """
        记录心跳

        Args:
            agent_id: Agent ID
            task_id: 任务 ID
            state: 当前状态
            interval: 心跳间隔（秒）
            timeout: 超时时间（秒）
        """
        from datetime import datetime

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO heartbeats
                   (agent_id, task_id, state, interval, timeout, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    agent_id,
                    task_id,
                    state,
                    interval,
                    timeout,
                    datetime.utcnow().isoformat() + "Z",
                ),
            )
            conn.commit()
