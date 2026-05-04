"""
状态机测试 — 11 状态版本

transition_to() 返回 None，非法转换抛 IllegalStateTransitionError。
"""

import pytest

from src.loop.state import AgentState, IllegalStateTransitionError, StateMachine


class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.state == AgentState.IDLE

    def test_valid_transition(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        assert sm.state == AgentState.PERCEIVING

    def test_invalid_transition_raises(self):
        sm = StateMachine()
        # IDLE 不能直接到 EXECUTING
        with pytest.raises(IllegalStateTransitionError):
            sm.transition_to(AgentState.EXECUTING)
        assert sm.state == AgentState.IDLE  # 状态不变

    def test_full_flow(self):
        """完整主循环：IDLE → PERCEIVING → ... → REPLYING → IDLE"""
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.EXECUTING)
        sm.transition_to(AgentState.OBSERVING)
        sm.transition_to(AgentState.REFLECTING)
        sm.transition_to(AgentState.REPLYING)
        sm.transition_to(AgentState.IDLE)
        assert sm.state == AgentState.IDLE

    def test_failed_recovery(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.FAILED)
        assert sm.state == AgentState.FAILED
        # FAILED → IDLE 合法
        sm.transition_to(AgentState.IDLE)
        assert sm.state == AgentState.IDLE

    def test_failed_to_reflecting(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.FAILED)
        sm.transition_to(AgentState.REFLECTING)
        assert sm.state == AgentState.REFLECTING

    def test_can_transition_to(self):
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.PERCEIVING) is True
        assert sm.can_transition_to(AgentState.EXECUTING) is False

    def test_clarifying_flow(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.CLARIFYING)
        assert sm.state == AgentState.CLARIFYING
        # CLARIFYING → UNDERSTANDING
        sm.transition_to(AgentState.UNDERSTANDING)
        assert sm.state == AgentState.UNDERSTANDING

    def test_waiting_approval_flow(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.WAITING_APPROVAL)
        assert sm.state == AgentState.WAITING_APPROVAL
        # WAITING_APPROVAL → EXECUTING（审批通过）
        sm.transition_to(AgentState.EXECUTING)
        assert sm.state == AgentState.EXECUTING

    def test_observing_retry(self):
        """OBSERVING → EXECUTING 跑偏重试"""
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        sm.transition_to(AgentState.EXECUTING)
        sm.transition_to(AgentState.OBSERVING)
        sm.transition_to(AgentState.EXECUTING)
        assert sm.state == AgentState.EXECUTING

    def test_history(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        history = sm.history
        assert len(history) == 2
        assert history[0][0] == "idle"
        assert history[0][1] == "perceiving"
        assert history[1][0] == "perceiving"
        assert history[1][1] == "understanding"

    def test_reset(self):
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.reset()
        assert sm.state == AgentState.IDLE
        assert len(sm.history) == 0

    def test_repr(self):
        sm = StateMachine()
        assert "idle" in repr(sm)
