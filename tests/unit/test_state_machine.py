"""
单元测试 — 状态机 (src/loop/state.py)

覆盖：
- AgentState 枚举
- StateMachine 初始化
- 合法状态转换
- 非法状态转换
- 历史记录
- can_transition_to()
"""

import pytest

from src.loop.state import (
    VALID_TRANSITIONS,
    AgentState,
    IllegalStateTransitionError,
    StateMachine,
)


class TestAgentState:
    """测试状态枚举"""

    def test_all_states_exist(self):
        states = [s.value for s in AgentState]
        expected = [
            "idle", "perceiving", "understanding", "planning",
            "executing", "observing", "reflecting", "replying",
            "waiting_approval", "clarifying", "failed",
        ]
        for s in expected:
            assert s in states

    def test_enum_values(self):
        assert AgentState.IDLE.value == "idle"
        assert AgentState.PERCEIVING.value == "perceiving"
        assert AgentState.FAILED.value == "failed"


class TestValidTransitions:
    """测试合法转换表"""

    def test_idle_can_go_to_perceiving(self):
        assert AgentState.PERCEIVING in VALID_TRANSITIONS[AgentState.IDLE]

    def test_perceiving_can_go_to_understanding(self):
        assert AgentState.UNDERSTANDING in VALID_TRANSITIONS[AgentState.PERCEIVING]

    def test_understanding_can_go_to_planning(self):
        assert AgentState.PLANNING in VALID_TRANSITIONS[AgentState.UNDERSTANDING]

    def test_planning_can_go_to_executing(self):
        assert AgentState.EXECUTING in VALID_TRANSITIONS[AgentState.PLANNING]

    def test_executing_can_go_to_observing(self):
        assert AgentState.OBSERVING in VALID_TRANSITIONS[AgentState.EXECUTING]

    def test_observing_can_go_to_reflecting(self):
        assert AgentState.REFLECTING in VALID_TRANSITIONS[AgentState.OBSERVING]

    def test_reflecting_can_go_to_replying(self):
        assert AgentState.REPLYING in VALID_TRANSITIONS[AgentState.REFLECTING]

    def test_replying_can_go_to_idle(self):
        assert AgentState.IDLE in VALID_TRANSITIONS[AgentState.REPLYING]

    def test_failed_can_recover_to_idle(self):
        assert AgentState.IDLE in VALID_TRANSITIONS[AgentState.FAILED]

    def test_waiting_approval_can_go_to_executing(self):
        assert AgentState.EXECUTING in VALID_TRANSITIONS[AgentState.WAITING_APPROVAL]


class TestStateMachineInit:
    def test_default_initial_state(self):
        sm = StateMachine()
        assert sm.state == AgentState.IDLE

    def test_custom_initial_state(self):
        sm = StateMachine(initial=AgentState.FAILED)
        assert sm.state == AgentState.FAILED

    def test_empty_history_on_init(self):
        sm = StateMachine()
        assert sm.history == []

    def test_has_timeout_manager(self):
        sm = StateMachine()
        assert sm.timeout_manager is not None

    def test_has_retry_policy(self):
        sm = StateMachine()
        assert sm.retry_policy is not None


class TestCanTransitionTo:
    def test_valid_transition(self):
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.PERCEIVING) is True

    def test_invalid_transition(self):
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.EXECUTING) is False

    def test_idle_cannot_go_to_failed(self):
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.FAILED) is False


class TestTransitionTo:
    def test_valid_transition(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        assert sm.state == AgentState.PERCEIVING

    def test_full_cycle(self):
        """完整状态循环"""
        sm = StateMachine()
        path = [
            AgentState.PERCEIVING,
            AgentState.UNDERSTANDING,
            AgentState.PLANNING,
            AgentState.EXECUTING,
            AgentState.OBSERVING,
            AgentState.REFLECTING,
            AgentState.REPLYING,
            AgentState.IDLE,
        ]
        for state in path:
            sm.transition_to(state)
        assert sm.state == AgentState.IDLE

    def test_invalid_transition_raises(self):
        sm = StateMachine()
        with pytest.raises(IllegalStateTransitionError):
            sm.transition_to(AgentState.EXECUTING)

    def test_records_history(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        assert len(sm.history) == 2
        assert sm.history[0][0] == "idle"
        assert sm.history[0][1] == "perceiving"
        assert sm.history[1][0] == "perceiving"
        assert sm.history[1][1] == "understanding"

    def test_failed_to_idle(self):
        sm = StateMachine(initial=AgentState.FAILED)
        sm.transition_to(AgentState.IDLE)
        assert sm.state == AgentState.IDLE

    def test_perceiving_to_failed(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.FAILED)
        assert sm.state == AgentState.FAILED

    def test_understanding_to_clarifying(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.CLARIFYING)
        assert sm.state == AgentState.CLARIFYING

    def test_clarifying_back_to_understanding(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.CLARIFYING)
        sm.transition_to(AgentState.UNDERSTANDING)
        assert sm.state == AgentState.UNDERSTANDING


class TestIllegalStateTransitionError:
    def test_message(self):
        err = IllegalStateTransitionError("test error")
        assert str(err) == "test error"
