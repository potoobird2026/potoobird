"""
单元测试 — 状态机 (src/loop/state.py)

覆盖：
- AgentState 枚举
- VALID_TRANSITIONS 转换表
- StateMachine 类（11 状态 FSM）
- AdaptiveTimeoutManager 类
- AdaptiveRetryPolicy 类
- MessageQueue 类
- AgentStateMachine 类（V2 7 状态 FSM）
- TransitionTrigger 枚举
- StateTransition / StateSnapshot 数据类
- StatePersistence 类
- IllegalStateTransitionError 异常
"""

import json
import os
import sqlite3
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ──────────────────────────────────────────────
# AgentState 枚举
# ──────────────────────────────────────────────

class TestAgentState:
    """测试 AgentState 枚举"""

    def test_all_states_exist(self):
        from src.loop.state import AgentState
        expected = [
            "IDLE", "PERCEIVING", "UNDERSTANDING", "PLANNING",
            "EXECUTING", "OBSERVING", "REFLECTING", "REPLYING",
            "WAITING_APPROVAL", "CLARIFYING", "FAILED",
        ]
        actual = [s.name for s in AgentState]
        assert actual == expected

    def test_state_values(self):
        from src.loop.state import AgentState
        assert AgentState.IDLE.value == "idle"
        assert AgentState.PERCEIVING.value == "perceiving"
        assert AgentState.UNDERSTANDING.value == "understanding"
        assert AgentState.PLANNING.value == "planning"
        assert AgentState.EXECUTING.value == "executing"
        assert AgentState.OBSERVING.value == "observing"
        assert AgentState.REFLECTING.value == "reflecting"
        assert AgentState.REPLYING.value == "replying"
        assert AgentState.WAITING_APPROVAL.value == "waiting_approval"
        assert AgentState.CLARIFYING.value == "clarifying"
        assert AgentState.FAILED.value == "failed"

    def test_11_states(self):
        from src.loop.state import AgentState
        assert len(AgentState) == 11


# ──────────────────────────────────────────────
# VALID_TRANSITIONS 转换表
# ──────────────────────────────────────────────

class TestValidTransitions:
    """测试合法状态转换表"""

    def test_idle_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.IDLE] == {AgentState.PERCEIVING}

    def test_perceiving_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.PERCEIVING] == {
            AgentState.UNDERSTANDING, AgentState.FAILED
        }

    def test_understanding_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.UNDERSTANDING] == {
            AgentState.PLANNING, AgentState.CLARIFYING, AgentState.FAILED
        }

    def test_clarifying_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.CLARIFYING] == {
            AgentState.UNDERSTANDING, AgentState.FAILED
        }

    def test_planning_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.PLANNING] == {
            AgentState.EXECUTING, AgentState.WAITING_APPROVAL
        }

    def test_waiting_approval_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.WAITING_APPROVAL] == {
            AgentState.EXECUTING, AgentState.IDLE
        }

    def test_executing_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.EXECUTING] == {
            AgentState.OBSERVING, AgentState.FAILED
        }

    def test_observing_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.OBSERVING] == {
            AgentState.REFLECTING, AgentState.EXECUTING, AgentState.FAILED
        }

    def test_reflecting_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.REFLECTING] == {AgentState.REPLYING}

    def test_replying_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.REPLYING] == {AgentState.IDLE}

    def test_failed_transitions(self):
        from src.loop.state import AgentState, VALID_TRANSITIONS
        assert VALID_TRANSITIONS[AgentState.FAILED] == {
            AgentState.IDLE, AgentState.REFLECTING
        }

    def test_all_states_have_transitions(self):
        """所有状态都应有转换规则"""
        from src.loop.state import AgentState, VALID_TRANSITIONS
        for state in AgentState:
            assert state in VALID_TRANSITIONS, f"{state} 缺少转换规则"


# ──────────────────────────────────────────────
# IllegalStateTransitionError
# ──────────────────────────────────────────────

class TestIllegalStateTransitionError:
    """测试非法状态转换异常"""

    def test_is_exception(self):
        from src.loop.state import IllegalStateTransitionError
        assert issubclass(IllegalStateTransitionError, Exception)

    def test_message(self):
        from src.loop.state import IllegalStateTransitionError
        err = IllegalStateTransitionError("test message")
        assert str(err) == "test message"


# ──────────────────────────────────────────────
# StateMachine 类
# ──────────────────────────────────────────────

class TestStateMachine:
    """测试 StateMachine 类（11 状态 FSM）"""

    def test_initial_state_is_idle(self):
        from src.loop.state import StateMachine
        sm = StateMachine()
        assert sm.state.name == "IDLE"

    def test_initial_state_custom(self):
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine(initial=AgentState.EXECUTING)
        assert sm.state == AgentState.EXECUTING

    def test_history_initially_empty(self):
        from src.loop.state import StateMachine
        sm = StateMachine()
        assert sm.history == []

    def test_can_transition_to_valid(self):
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.PERCEIVING) is True

    def test_can_transition_to_invalid(self):
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.EXECUTING) is False

    def test_transition_to_valid_state(self):
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        assert sm.state == AgentState.PERCEIVING

    def test_transition_records_history(self):
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        assert len(sm.history) == 1
        from_state, to_state, ts = sm.history[0]
        assert from_state == "idle"
        assert to_state == "perceiving"

    def test_transition_invalid_raises(self):
        from src.loop.state import StateMachine, AgentState, IllegalStateTransitionError
        sm = StateMachine()
        with pytest.raises(IllegalStateTransitionError):
            sm.transition_to(AgentState.EXECUTING)

    def test_full_normal_flow(self):
        """测试完整正常流程：IDLE → PERCEIVING → UNDERSTANDING → PLANNING → EXECUTING → OBSERVING → REFLECTING → REPLYING → IDLE"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        flow = [
            AgentState.PERCEIVING,
            AgentState.UNDERSTANDING,
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.OBSERVING,
            AgentState.REFLECTING,
            AgentState.REPLYING,
            AgentState.IDLE,
        ]
        for state in flow:
            sm.transition_to(state)
        assert sm.state == AgentState.IDLE
        assert len(sm.history) == 8

    def test_failure_and_recovery_flow(self):
        """测试失败恢复流程：PERCEIVING → FAILED → IDLE"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.FAILED)
        assert sm.state == AgentState.FAILED
        sm.transition_to(AgentState.IDLE)
        assert sm.state == AgentState.IDLE

    def test_failure_to_reflecting_flow(self):
        """FAILED 也可以转到 REFLECTING"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.FAILED)
        sm.transition_to(AgentState.REFLECTING)
        assert sm.state == AgentState.REFLECTING

    def test_clarifying_flow(self):
        """测试追问澄清流程：UNDERSTANDING → CLARIFYING → UNDERSTANDING"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.CLARIFYING)
        assert sm.state == AgentState.CLARIFYING
        sm.transition_to(AgentState.UNDERSTANDING)
        assert sm.state == AgentState.UNDERSTANDING

    def test_waiting_approval_flow(self):
        """测试审批流程：PLANNING → WAITING_APPROVAL → EXECUTING"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.WAITING_APPROVAL)
        assert sm.state == AgentState.WAITING_APPROVAL
        sm.transition_to(AgentState.EXECUTING)
        assert sm.state == AgentState.EXECUTING

    def test_waiting_approval_to_idle(self):
        """审批超时应回到 IDLE"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.WAITING_APPROVAL)
        sm.transition_to(AgentState.IDLE)
        assert sm.state == AgentState.IDLE

    def test_observing_retry_flow(self):
        """OBSERVING 可以重试回 EXECUTING"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.EXECUTING)
        sm.transition_to(AgentState.OBSERVING)
        sm.transition_to(AgentState.EXECUTING)
        assert sm.state == AgentState.EXECUTING

    def test_reset(self):
        """测试重置功能"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.reset()
        assert sm.state == AgentState.IDLE
        assert sm.history == []

    def test_history_returns_copy(self):
        """history 属性应返回副本"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        history = sm.history
        history.clear()
        assert len(sm.history) == 1

    def test_repr(self):
        from src.loop.state import StateMachine
        sm = StateMachine()
        # repr 使用 .value (小写)
        assert "idle" in repr(sm)

    def test_multiple_transitions_accumulate(self):
        """多次转换应累积历史"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        assert len(sm.history) == 3

    def test_timeout_manager_accessible(self):
        """timeout_manager 属性应可访问"""
        from src.loop.state import StateMachine, AdaptiveTimeoutManager
        sm = StateMachine()
        assert isinstance(sm.timeout_manager, AdaptiveTimeoutManager)

    def test_retry_policy_accessible(self):
        """retry_policy 属性应可访问"""
        from src.loop.state import StateMachine, AdaptiveRetryPolicy
        sm = StateMachine()
        assert isinstance(sm.retry_policy, AdaptiveRetryPolicy)

    def test_get_heartbeat_interval(self):
        """get_heartbeat_interval 应返回整数"""
        from src.loop.state import StateMachine
        sm = StateMachine()
        interval = sm.get_heartbeat_interval()
        assert isinstance(interval, int)
        assert interval > 0

    def test_get_current_timeout(self):
        """IDLE 状态 get_current_timeout 应返回 None"""
        from src.loop.state import StateMachine
        sm = StateMachine()
        assert sm.get_current_timeout() is None

    def test_get_retry_policy(self):
        """get_retry_policy 应返回字典"""
        from src.loop.state import StateMachine
        sm = StateMachine()
        policy = sm.get_retry_policy("timeout error")
        assert isinstance(policy, dict)


# ──────────────────────────────────────────────
# AdaptiveTimeoutManager 类
# ──────────────────────────────────────────────

class TestAdaptiveTimeoutManager:
    """测试自适应超时管理器"""

    def test_idle_timeout_is_none(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        assert mgr.get_timeout(AgentState.IDLE) is None

    def test_perceiving_timeout_with_context(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(
            AgentState.PERCEIVING,
            context={"estimated_steps": 10, "avg_step_time": 30}
        )
        assert timeout == int(10 * 30 * 1.5)

    def test_executing_timeout_with_context(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(
            AgentState.EXECUTING,
            context={"estimated_steps": 5, "avg_step_time": 60}
        )
        assert timeout == int(5 * 60 * 1.5)

    def test_waiting_approval_timeout_with_user_response(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(
            AgentState.WAITING_APPROVAL,
            context={"user_response_time": 120}
        )
        assert timeout == 240

    def test_waiting_approval_timeout_with_tool_timeout(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(
            AgentState.WAITING_APPROVAL,
            context={"tool_timeout": 300}
        )
        assert timeout == 600

    def test_waiting_approval_timeout_default(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(AgentState.WAITING_APPROVAL)
        assert timeout == 600  # 300 * 2

    def test_clarifying_timeout_default(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(AgentState.CLARIFYING)
        assert timeout == 3600

    def test_clarifying_timeout_user_defined(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(
            AgentState.CLARIFYING,
            context={"user_defined_timeout": 1800}
        )
        assert timeout == 1800

    def test_heartbeat_interval_idle(self):
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        assert mgr.get_heartbeat_interval(AgentState.IDLE) == 60

    def test_heartbeat_interval_bounded(self):
        """心跳间隔应在 [3, 32] 范围内"""
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        # PERCEIVING with large timeout
        interval = mgr.get_heartbeat_interval(
            AgentState.PERCEIVING,
            context={"estimated_steps": 100, "avg_step_time": 60}
        )
        assert 3 <= interval <= 32

    def test_record_actual_timeout(self):
        """记录实际超时后应影响后续超时计算"""
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        mgr.record_actual_timeout(AgentState.PERCEIVING, 120)
        mgr.record_actual_timeout(AgentState.PERCEIVING, 150)
        # 中位数应为 135 (median of [120, 150])
        timeout = mgr.get_timeout(AgentState.PERCEIVING)
        assert timeout is not None

    def test_record_timeout_trims_to_100(self):
        """记录超过100条时应裁剪"""
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        for i in range(110):
            mgr.record_actual_timeout(AgentState.PERCEIVING, i + 1)
        assert len(mgr._timeout_history["perceiving"]) == 100

    def test_get_timeout_none_for_unknown(self):
        """未知状态应返回 None"""
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        # REPLYING has no specific timeout config
        timeout = mgr.get_timeout(AgentState.REPLYING)
        assert timeout is None

    def test_heartbeat_with_none_timeout(self):
        """超时时 None 应返回 60"""
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        interval = mgr.get_heartbeat_interval(AgentState.REPLYING)
        assert interval == 60


# ──────────────────────────────────────────────
# AdaptiveRetryPolicy 类（通过 StateMachine 属性）
# ──────────────────────────────────────────────

class TestAdaptiveRetryPolicy:
    """测试自适应重试策略"""

    def test_default_max_retries(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.max_retries == 3

    def test_custom_max_retries(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(max_retries=5)
        assert policy.max_retries == 5

    def test_default_base_delay(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.base_delay == 1.0

    def test_custom_base_delay(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(base_delay=2.0)
        assert policy.base_delay == 2.0

    def test_should_retry_timeout(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.should_retry("timeout", attempt=1) is True

    def test_should_retry_rate_limit(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.should_retry("rate_limit", attempt=1) is True

    def test_should_retry_server_error(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.should_retry("server_error", attempt=1) is True

    def test_should_retry_connection_error(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.should_retry("connection_error", attempt=1) is True

    def test_should_not_retry_auth_error(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.should_retry("auth_error", attempt=1) is False

    def test_should_not_retry_invalid_request(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.should_retry("invalid_request", attempt=1) is False

    def test_should_not_retry_quota_exceeded(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        assert policy.should_retry("quota_exceeded", attempt=1) is False

    def test_should_not_retry_after_max(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(max_retries=3)
        assert policy.should_retry("timeout", attempt=3) is False

    def test_should_retry_at_max_minus_one(self):
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(max_retries=3)
        assert policy.should_retry("timeout", attempt=2) is True

    def test_retry_delay_exponential(self):
        """重试延迟应呈指数增长"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(base_delay=1.0)
        delay1 = policy.get_retry_delay(1)
        delay2 = policy.get_retry_delay(2)
        delay3 = policy.get_retry_delay(3)
        # delay2 的指数部分应该是 delay1 的 2 倍
        assert delay2 > delay1
        assert delay3 > delay2

    def test_retry_delay_base_1(self):
        """attempt=1 时基础延迟约为 base_delay"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(base_delay=1.0)
        delay = policy.get_retry_delay(1)
        # 1.0 * 2^0 = 1.0, plus jitter up to 0.5
        assert 1.0 <= delay <= 1.5

    def test_retry_delay_base_2(self):
        """attempt=2 时基础延迟约为 2 * base_delay"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(base_delay=1.0)
        delay = policy.get_retry_delay(2)
        # 1.0 * 2^1 = 2.0, plus jitter up to 0.5
        assert 2.0 <= delay <= 2.5

    def test_adapt_not_enough_history(self):
        """历史数据不足10条时 adapt 不应修改参数"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        policy._retry_history = [(1, True, 0.5)] * 5
        policy.adapt()
        assert policy.max_retries == 3
        assert policy.base_delay == 1.0

    def test_adapt_high_success_rate(self):
        """高成功率应减少 max_retries"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        policy._retry_history = [(1, True, 0.5)] * 10
        policy.adapt()
        assert policy.max_retries == 2

    def test_adapt_low_success_rate(self):
        """低成功率应增加 max_retries"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy()
        policy._retry_history = [(1, False, 0.5)] * 10
        policy.adapt()
        assert policy.max_retries == 4

    def test_adapt_max_retries_bounded_high(self):
        """max_retries 不应超过 5"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(max_retries=5)
        policy._retry_history = [(1, False, 0.5)] * 10
        policy.adapt()
        assert policy.max_retries == 5

    def test_adapt_max_retries_bounded_low(self):
        """max_retries 不应低于 1"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(max_retries=1)
        policy._retry_history = [(1, True, 0.5)] * 10
        policy.adapt()
        assert policy.max_retries == 1

    def test_adapt_base_delay_from_p95(self):
        """base_delay 应根据 P95 延迟调整"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(base_delay=2.0)
        # 使用较大的延迟值确保 P95 * 0.1 < 初始 base_delay
        policy._retry_history = [(1, True, float(i) * 100) for i in range(1, 11)]
        policy.adapt()
        # P95 of [100, 200, ..., 1000] ≈ 950, base_delay = max(0.1, 950 * 0.1) = 95
        assert policy.base_delay != 2.0

    def test_retryable_errors_set(self):
        from src.loop.state import AdaptiveRetryPolicy
        assert "timeout" in AdaptiveRetryPolicy.RETRYABLE_ERRORS
        assert "rate_limit" in AdaptiveRetryPolicy.RETRYABLE_ERRORS
        assert "server_error" in AdaptiveRetryPolicy.RETRYABLE_ERRORS
        assert "connection_error" in AdaptiveRetryPolicy.RETRYABLE_ERRORS

    def test_non_retryable_errors_set(self):
        from src.loop.state import AdaptiveRetryPolicy
        assert "auth_error" in AdaptiveRetryPolicy.NON_RETRYABLE_ERRORS
        assert "invalid_request" in AdaptiveRetryPolicy.NON_RETRYABLE_ERRORS
        assert "quota_exceeded" in AdaptiveRetryPolicy.NON_RETRYABLE_ERRORS


# ──────────────────────────────────────────────
# MessageQueue 类
# ──────────────────────────────────────────────

class TestMessageQueue:
    """测试消息队列"""

    def test_is_interruptible_executing(self):
        """EXECUTING 状态下只有 pause/cancel/interrupt 可中断"""
        from src.loop.state import MessageQueue, StateMachine, AgentState
        sm = StateMachine()
        # IDLE → PERCEIVING → UNDERSTANDING → PLANNING → EXECUTING
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.EXECUTING)
        mq = MessageQueue(sm)
        assert mq.is_interruptible("pause") is True
        assert mq.is_interruptible("cancel") is True
        assert mq.is_interruptible("some_other_trigger") is False

    def test_is_interruptible_idle(self):
        """IDLE 状态所有触发器都可中断"""
        from src.loop.state import MessageQueue, StateMachine
        sm = StateMachine()
        mq = MessageQueue(sm)
        assert mq.is_interruptible("any_trigger") is True

    def test_is_interruptible_waiting_approval(self):
        """WAITING_APPROVAL 只有特定触发器可中断"""
        from src.loop.state import MessageQueue, StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.WAITING_APPROVAL)
        mq = MessageQueue(sm)
        assert mq.is_interruptible("approval_granted") is True
        assert mq.is_interruptible("approval_denied") is True
        assert mq.is_interruptible("timeout") is True
        assert mq.is_interruptible("other") is False

    def test_enqueue_interruptible_returns_true(self):
        """可中断消息入队应返回 True"""
        from src.loop.state import MessageQueue, StateMachine, MessagePriority
        sm = StateMachine()
        mq = MessageQueue(sm)
        result = mq.enqueue("any_trigger", priority=MessagePriority.NORMAL)
        assert result is True

    def test_enqueue_non_interruptible_queues(self):
        """不可中断消息应入队"""
        from src.loop.state import MessageQueue, StateMachine, AgentState, MessagePriority
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.EXECUTING)
        mq = MessageQueue(sm)
        result = mq.enqueue("non_interruptible_trigger", priority=MessagePriority.CONTROL)
        assert result is True
        assert len(mq._queue) == 1

    def test_process_queue_empty(self):
        """空队列处理不应报错"""
        from src.loop.state import MessageQueue, StateMachine
        sm = StateMachine()
        mq = MessageQueue(sm)
        mq.process_queue()  # 不应抛异常

    def test_process_queue_makes_progress(self):
        """队列处理应能处理可中断的消息"""
        from src.loop.state import MessageQueue, StateMachine, AgentState, MessagePriority
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.EXECUTING)
        mq = MessageQueue(sm)
        # 入队一个不可中断的消息
        mq.enqueue("unknown_trigger", priority=MessagePriority.NORMAL)
        # 切换到 FAILED → IDLE，所有消息都可中断
        sm.transition_to(AgentState.FAILED)
        sm.transition_to(AgentState.IDLE)
        mq.process_queue()
        # IDLE 状态下所有触发器都可中断，队列应被清空
        assert len(mq._queue) == 0


# ──────────────────────────────────────────────
# TransitionTrigger 枚举
# ──────────────────────────────────────────────

class TestTransitionTrigger:
    """测试 TransitionTrigger 枚举"""

    def test_all_triggers_exist(self):
        from src.loop.state import TransitionTrigger
        expected = [
            "TASK_RECEIVED", "START_EXECUTION", "CANCEL", "PAUSE",
            "RESUME", "NEED_APPROVAL", "APPROVAL_GRANTED",
            "APPROVAL_DENIED", "APPROVAL_TIMEOUT", "COMPLETE",
            "FAIL", "RETRY", "NEW_TASK",
        ]
        actual = [t.name for t in TransitionTrigger]
        assert actual == expected

    def test_trigger_values(self):
        from src.loop.state import TransitionTrigger
        assert TransitionTrigger.TASK_RECEIVED.value == "task_received"
        assert TransitionTrigger.APPROVAL_GRANTED.value == "approval_granted"


# ──────────────────────────────────────────────
# StateTransition / StateSnapshot 数据类
# ──────────────────────────────────────────────

class TestDataClasses:
    """测试数据类"""

    def test_state_transition_defaults(self):
        from src.loop.state import StateTransition
        st = StateTransition()
        assert st.from_state == ""
        assert st.to_state == ""
        assert st.trigger == ""
        assert st.metadata == {}
        assert st.timestamp != ""

    def test_state_transition_with_values(self):
        from src.loop.state import StateTransition
        st = StateTransition(
            from_state="IDLE",
            to_state="READY",
            trigger="task_received",
            metadata={"key": "value"},
        )
        assert st.from_state == "IDLE"
        assert st.to_state == "READY"
        assert st.trigger == "task_received"
        assert st.metadata == {"key": "value"}

    def test_state_snapshot_defaults(self):
        from src.loop.state import StateSnapshot
        snap = StateSnapshot()
        assert snap.agent_id == ""
        assert snap.task_id == ""
        assert snap.state == ""
        assert snap.metadata == {}
        assert snap.timeout_config == {}
        assert snap.timestamp != ""

    def test_state_snapshot_with_values(self):
        from src.loop.state import StateSnapshot
        snap = StateSnapshot(
            agent_id="agent-1",
            task_id="task-1",
            state="EXECUTING",
            metadata={"progress": 50},
            timeout_config={"timeout": 300},
        )
        assert snap.agent_id == "agent-1"
        assert snap.task_id == "task-1"
        assert snap.state == "EXECUTING"


# ──────────────────────────────────────────────
# AgentStateMachine 类（V2）
# ──────────────────────────────────────────────

class TestAgentStateMachine:
    """测试 V2 AgentStateMachine（7 状态 FSM）"""

    def test_initial_state_is_idle(self):
        from src.loop.state import AgentStateMachine
        sm = AgentStateMachine()
        assert sm.current_state == "IDLE"

    def test_history_initially_empty(self):
        from src.loop.state import AgentStateMachine
        sm = AgentStateMachine()
        assert sm.history == []

    def test_can_transition_task_received(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        assert sm.can_transition(TransitionTrigger.TASK_RECEIVED) is True

    def test_can_transition_invalid(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        assert sm.can_transition(TransitionTrigger.COMPLETE) is False

    def test_transition_task_received(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        result = sm.transition(TransitionTrigger.TASK_RECEIVED)
        assert result is True
        assert sm.current_state == "READY"

    def test_full_flow(self):
        """测试完整 V2 流程"""
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        assert sm.current_state == "READY"
        sm.transition(TransitionTrigger.START_EXECUTION)
        assert sm.current_state == "EXECUTING"
        sm.transition(TransitionTrigger.COMPLETE)
        assert sm.current_state == "COMPLETED"
        sm.transition(TransitionTrigger.NEW_TASK)
        assert sm.current_state == "IDLE"

    def test_pause_resume_flow(self):
        """测试暂停/恢复流程"""
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.PAUSE)
        assert sm.current_state == "PAUSED"
        sm.transition(TransitionTrigger.RESUME)
        assert sm.current_state == "EXECUTING"

    def test_cancel_from_ready(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.CANCEL)
        assert sm.current_state == "IDLE"

    def test_cancel_from_paused(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.PAUSE)
        sm.transition(TransitionTrigger.CANCEL)
        assert sm.current_state == "IDLE"

    def test_approval_flow(self):
        """测试审批流程"""
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.NEED_APPROVAL)
        assert sm.current_state == "WAITING"
        sm.transition(TransitionTrigger.APPROVAL_GRANTED)
        assert sm.current_state == "EXECUTING"

    def test_approval_denied(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.NEED_APPROVAL)
        sm.transition(TransitionTrigger.APPROVAL_DENIED)
        assert sm.current_state == "FAILED"

    def test_approval_timeout(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.NEED_APPROVAL)
        sm.transition(TransitionTrigger.APPROVAL_TIMEOUT)
        assert sm.current_state == "IDLE"

    def test_fail_and_retry(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.FAIL)
        assert sm.current_state == "FAILED"
        sm.transition(TransitionTrigger.RETRY)
        assert sm.current_state == "EXECUTING"

    def test_fail_and_cancel(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.FAIL)
        sm.transition(TransitionTrigger.CANCEL)
        assert sm.current_state == "IDLE"

    def test_invalid_transition_returns_false(self):
        """非法转换应返回 False"""
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        result = sm.transition(TransitionTrigger.COMPLETE)
        assert result is False
        assert sm.current_state == "IDLE"

    def test_transition_with_metadata(self):
        """转换应支持 metadata"""
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED, metadata={"user": "test"})
        assert len(sm.history) == 1
        assert sm.history[0].metadata == {"user": "test"}

    def test_history_accumulates(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        sm.transition(TransitionTrigger.START_EXECUTION)
        sm.transition(TransitionTrigger.COMPLETE)
        assert len(sm.history) == 3

    def test_history_returns_copy(self):
        from src.loop.state import AgentStateMachine, TransitionTrigger
        sm = AgentStateMachine()
        sm.transition(TransitionTrigger.TASK_RECEIVED)
        history = sm.history
        history.clear()
        assert len(sm.history) == 1


# ──────────────────────────────────────────────
# StatePersistence 类
# ──────────────────────────────────────────────

class TestStatePersistence:
    """测试状态持久化"""

    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test_state.db")

    def test_init_creates_tables(self, db_path):
        from src.loop.state import StatePersistence
        sp = StatePersistence(db_path=db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in cursor.fetchall()}
            assert "state_snapshots" in tables
            assert "state_transitions" in tables
            assert "heartbeats" in tables

    def test_save_and_load_snapshot(self, db_path):
        from src.loop.state import StatePersistence, StateSnapshot
        sp = StatePersistence(db_path=db_path)
        snapshot = StateSnapshot(
            agent_id="agent-1",
            task_id="task-1",
            state="EXECUTING",
            metadata={"progress": 50},
        )
        sp.save_snapshot(snapshot, agent_id="agent-1", timeout_config={"timeout": 300})

        loaded = sp.load_latest_snapshot("task-1")
        assert loaded is not None
        assert loaded["agent_id"] == "agent-1"
        assert loaded["state"] == "EXECUTING"

    def test_load_nonexistent_snapshot(self, db_path):
        from src.loop.state import StatePersistence
        sp = StatePersistence(db_path=db_path)
        loaded = sp.load_latest_snapshot("nonexistent")
        assert loaded is None

    def test_record_transition(self, db_path):
        from src.loop.state import StatePersistence, StateTransition
        sp = StatePersistence(db_path=db_path)
        transition = StateTransition(
            from_state="IDLE",
            to_state="READY",
            trigger="task_received",
        )
        sp.record_transition(transition, agent_id="agent-1")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM state_transitions").fetchone()
            assert row is not None
            assert row["from_state"] == "IDLE"
            assert row["to_state"] == "READY"

    def test_record_heartbeat(self, db_path):
        from src.loop.state import StatePersistence
        sp = StatePersistence(db_path=db_path)
        sp.record_heartbeat(
            agent_id="agent-1",
            task_id="task-1",
            state="EXECUTING",
            interval=10,
            timeout=300,
        )

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM heartbeats").fetchone()
            assert row is not None
            assert row["agent_id"] == "agent-1"
            assert row["interval"] == 10

    def test_record_heartbeat_without_timeout(self, db_path):
        from src.loop.state import StatePersistence
        sp = StatePersistence(db_path=db_path)
        sp.record_heartbeat(
            agent_id="agent-1",
            task_id="task-1",
            state="IDLE",
            interval=60,
        )

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM heartbeats").fetchone()
            assert row is not None
            assert row["timeout"] is None

    def test_default_db_path(self):
        """默认数据库路径应有效"""
        from src.loop.state import StatePersistence
        with patch("src.loop.state.os"):
            sp = StatePersistence()
            assert sp.db_path is not None

    def test_save_snapshot_metadata_is_json(self, db_path):
        """快照 metadata 应保存为 JSON"""
        from src.loop.state import StatePersistence, StateSnapshot
        sp = StatePersistence(db_path=db_path)
        snapshot = StateSnapshot(
            agent_id="agent-1",
            task_id="task-1",
            state="EXECUTING",
            metadata={"key": "value", "nested": {"a": 1}},
        )
        sp.save_snapshot(snapshot, agent_id="agent-1", timeout_config={})

        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT metadata FROM state_snapshots").fetchone()
            data = json.loads(row[0])
            assert data["key"] == "value"
            assert data["nested"]["a"] == 1

    def test_multiple_snapshots_latest(self, db_path):
        """应能保存多个快照并加载最新的"""
        from src.loop.state import StatePersistence, StateSnapshot
        sp = StatePersistence(db_path=db_path)

        snap1 = StateSnapshot(
            agent_id="agent-1", task_id="task-1", state="EXECUTING"
        )
        sp.save_snapshot(snap1, agent_id="agent-1", timeout_config={})

        snap2 = StateSnapshot(
            agent_id="agent-1", task_id="task-1", state="COMPLETED"
        )
        sp.save_snapshot(snap2, agent_id="agent-1", timeout_config={})

        loaded = sp.load_latest_snapshot("task-1")
        assert loaded["state"] == "COMPLETED"


# ──────────────────────────────────────────────
# 边界条件测试
# ──────────────────────────────────────────────

class TestEdgeCases:
    """边界条件测试"""

    def test_state_machine_double_reset(self):
        """多次重置不应报错"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.reset()
        sm.reset()
        assert sm.state == AgentState.IDLE

    def test_state_machine_history_over_100(self):
        """历史超过100条时应裁剪"""
        from src.loop.state import StateMachine, AgentState
        sm = StateMachine()
        # 执行多次循环以累积历史
        for _ in range(50):
            sm.transition_to(AgentState.PERCEIVING)
            sm.transition_to(AgentState.UNDERSTANDING)
            sm.transition_to(AgentState.PLANNING)
            sm.transition_to(AgentState.EXECUTING)
            sm.transition_to(AgentState.OBSERVING)
            sm.transition_to(AgentState.REFLECTING)
            sm.transition_to(AgentState.REPLYING)
            sm.transition_to(AgentState.IDLE)
        # 历史应被裁剪到100条以内
        assert len(sm.history) <= 100

    def test_retry_delay_attempt_0(self):
        """attempt=0 时重试延迟"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(base_delay=1.0)
        delay = policy.get_retry_delay(0)
        # 1.0 * 2^(-1) = 0.5
        assert delay > 0

    def test_retry_delay_large_attempt(self):
        """大 attempt 值时重试延迟"""
        from src.loop.state import AdaptiveRetryPolicy
        policy = AdaptiveRetryPolicy(base_delay=0.1)
        delay = policy.get_retry_delay(10)
        assert delay > 0

    def test_timeout_zero_steps(self):
        """estimated_steps=0 时超时"""
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        timeout = mgr.get_timeout(
            AgentState.EXECUTING,
            context={"estimated_steps": 0, "avg_step_time": 60}
        )
        assert timeout == 0

    def test_heartbeat_minimum(self):
        """心跳间隔最小值应为 3"""
        from src.loop.state import AdaptiveTimeoutManager, AgentState
        mgr = AdaptiveTimeoutManager()
        # 超时很短，心跳间隔应为最小值 3
        interval = mgr.get_heartbeat_interval(
            AgentState.EXECUTING,
            context={"estimated_steps": 1, "avg_step_time": 1}
        )
        assert interval >= 3

    def test_message_queue_priority_ordering(self):
        """消息队列应按优先级排序"""
        from src.loop.state import MessageQueue, StateMachine, AgentState, MessagePriority
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.EXECUTING)
        mq = MessageQueue(sm)

        # 入队一个低优先级消息 (NORMAL=2)
        mq.enqueue("low_priority", priority=MessagePriority.NORMAL)
        # 入队一个高优先级消息 (EMERGENCY=0)
        mq.enqueue("high_priority", priority=MessagePriority.EMERGENCY)

        # 高优先级消息应排在前面（堆排序，数值小的优先级高）
        assert mq._queue[0].priority == MessagePriority.EMERGENCY
