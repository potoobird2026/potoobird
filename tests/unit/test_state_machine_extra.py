"""
状态机补充测试 — 提升 src/loop/state.py 覆盖率

覆盖：
- StateMachine 进入/退出动作
- AdaptiveTimeoutManager 完整功能
- AdaptiveRetryPolicy 完整功能
- 状态机消息队列功能
- 心跳间隔计算
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from src.loop.state import (
    AdaptiveTimeoutManager,
    AdaptiveRetryPolicy,
    AgentState,
    IllegalStateTransitionError,
    StateMachine,
    VALID_TRANSITIONS,
)


class TestStateMachineEnterExitActions:
    """测试状态机进入/退出动作"""

    def test_on_enter_idle_truncates_history(self):
        """进入 IDLE 时历史超过100条应裁剪"""
        sm = StateMachine()
        # 填充超过100条历史
        for i in range(105):
            sm._history.append(("idle", "perceiving", "2024-01-01T00:00:00Z"))
        sm._on_enter_state(AgentState.IDLE)
        assert len(sm._history) == 100

    def test_on_enter_idle_keeps_under_100(self):
        """进入 IDLE 时历史不足100条不裁剪"""
        sm = StateMachine()
        initial_len = len(sm._history)  # 初始化时可能已有历史
        sm._history.append(("idle", "perceiving", "2024-01-01T00:00:00Z"))
        sm._on_enter_state(AgentState.IDLE)
        # 不足100条时不应裁剪
        assert len(sm._history) == initial_len + 1

    def test_on_exit_state_records_elapsed(self):
        """退出状态应记录耗时"""
        sm = StateMachine()
        sm._state_entry_time[AgentState.PERCEIVING.value] = time.time() - 5
        sm._on_exit_state(AgentState.PERCEIVING)
        # 记录后应从 _state_entry_time 中删除
        assert AgentState.PERCEIVING.value not in sm._state_entry_time

    def test_on_exit_failed_logs_warning(self):
        """退出 FAILED 状态应记录警告"""
        sm = StateMachine()
        with patch("src.loop.state.logger") as mock_logger:
            sm._on_exit_state(AgentState.FAILED)
            mock_logger.warning.assert_called_once()

    def test_on_enter_waiting_approval(self):
        """进入 WAITING_APPROVAL 应设置超时"""
        sm = StateMachine()
        with patch("src.loop.state.logger") as mock_logger:
            sm._on_enter_state(AgentState.WAITING_APPROVAL)
            mock_logger.info.assert_called()

    def test_on_enter_clarifying(self):
        """进入 CLARIFYING 应设置超时"""
        sm = StateMachine()
        with patch("src.loop.state.logger") as mock_logger:
            sm._on_enter_state(AgentState.CLARIFYING)
            mock_logger.info.assert_called()

    def test_on_enter_failed(self):
        """进入 FAILED 应记录警告"""
        sm = StateMachine()
        with patch("src.loop.state.logger") as mock_logger:
            sm._on_enter_state(AgentState.FAILED)
            mock_logger.warning.assert_called()


class TestStateMachineReset:
    """测试状态机重置"""

    def test_reset_clears_history(self):
        """重置应清空历史"""
        sm = StateMachine()
        sm._history.append(("idle", "perceiving", "2024-01-01T00:00:00Z"))
        sm.reset()
        assert sm.history == []

    def test_reset_clears_entry_times(self):
        """重置应清空进入时间"""
        sm = StateMachine()
        sm._state_entry_time["test"] = time.time()
        sm.reset()
        assert sm._state_entry_time == {}

    def test_reset_to_idle(self):
        """重置后状态应为 IDLE"""
        sm = StateMachine(initial=AgentState.FAILED)
        sm.reset()
        assert sm.state == AgentState.IDLE


class TestStateMachineTransitionRecording:
    """测试状态转换历史记录"""

    def test_transition_appends_to_history(self):
        """转换应追加到历史"""
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        assert len(sm.history) > 0
        last = sm.history[-1]
        assert last[0] == "idle"
        assert last[1] == "perceiving"

    def test_transition_includes_timestamp(self):
        """历史记录应包含时间戳"""
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        last = sm.history[-1]
        assert len(last) == 3  # (from, to, timestamp)
        assert "T" in last[2]  # ISO 格式时间戳

    def test_multiple_transitions_recorded(self):
        """多次转换应全部记录"""
        sm = StateMachine()
        sm.transition_to(AgentState.PERCEIVING)
        sm.transition_to(AgentState.UNDERSTANDING)
        sm.transition_to(AgentState.PLANNING)
        # 初始有 IDLE 进入的历史 + 3次转换
        assert len(sm.history) >= 3


class TestStateMachineCanTransition:
    """测试 can_transition_to"""

    def test_all_valid_transitions(self):
        """所有合法转换应返回 True"""
        for from_state, to_states in VALID_TRANSITIONS.items():
            for to_state in to_states:
                sm = StateMachine(initial=from_state)
                assert sm.can_transition_to(to_state) is True, \
                    f"{from_state.value} → {to_state.value} 应合法"

    def test_invalid_transition_idle_to_executing(self):
        """IDLE 不能直接到 EXECUTING"""
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.EXECUTING) is False

    def test_invalid_transition_idle_to_failed(self):
        """IDLE 不能直接到 FAILED"""
        sm = StateMachine()
        assert sm.can_transition_to(AgentState.FAILED) is False

    def test_invalid_transition_replying_to_executing(self):
        """REPLYING 不能直接到 EXECUTING"""
        sm = StateMachine(initial=AgentState.REPLYING)
        assert sm.can_transition_to(AgentState.EXECUTING) is False


class TestStateMachineIllegalTransition:
    """测试非法转换异常"""

    def test_illegal_transition_raises(self):
        """非法转换应抛出异常"""
        sm = StateMachine()
        with pytest.raises(IllegalStateTransitionError):
            sm.transition_to(AgentState.EXECUTING)

    def test_illegal_transition_error_message(self):
        """异常信息应包含当前状态和目标状态"""
        sm = StateMachine()
        with pytest.raises(IllegalStateTransitionError) as exc_info:
            sm.transition_to(AgentState.FAILED)
        assert "idle" in str(exc_info.value)
        assert "failed" in str(exc_info.value)


class TestStateMachineProperties:
    """测试状态机属性"""

    def test_state_property(self):
        """state 属性应返回当前状态"""
        sm = StateMachine()
        assert sm.state == AgentState.IDLE

    def test_history_property_returns_copy(self):
        """history 属性应返回副本"""
        sm = StateMachine()
        h = sm.history
        h.append(("test", "test", "test"))
        # 修改返回的列表不应影响内部状态
        assert len(sm.history) != len(h)

    def test_timeout_manager_property(self):
        """timeout_manager 属性应返回管理器"""
        sm = StateMachine()
        assert sm.timeout_manager is not None

    def test_retry_policy_property(self):
        """retry_policy 属性应返回重试策略"""
        sm = StateMachine()
        assert sm.retry_policy is not None


class TestAdaptiveTimeoutManager:
    """自适应超时管理器测试"""

    def test_default_timeouts(self):
        """默认超时时间"""
        mgr = AdaptiveTimeoutManager()
        # IDLE 应无超时
        assert mgr.get_timeout(AgentState.IDLE) is None

    def test_get_heartbeat_interval(self):
        """获取心跳间隔"""
        mgr = AdaptiveTimeoutManager()
        interval = mgr.get_heartbeat_interval(AgentState.IDLE)
        assert isinstance(interval, int)
        assert interval > 0

    def test_record_actual_timeout(self):
        """记录实际超时"""
        mgr = AdaptiveTimeoutManager()
        mgr.record_actual_timeout(AgentState.PERCEIVING, 10)
        # 不应抛出异常

    def test_get_current_timeout(self):
        """获取当前状态超时"""
        sm = StateMachine()
        timeout = sm.get_current_timeout()
        # IDLE 应无超时
        assert timeout is None


class TestAdaptiveRetryPolicy:
    """自适应重试策略测试"""

    def test_get_retry_policy_tool_failure(self):
        """工具失败重试策略"""
        policy = AdaptiveRetryPolicy()
        result = policy.get_retry_policy("tool_failure")
        assert isinstance(result, dict)
        assert "max_retries" in result

    def test_get_retry_policy_llm_failure(self):
        """LLM 失败重试策略"""
        policy = AdaptiveRetryPolicy()
        result = policy.get_retry_policy("llm_failure")
        assert isinstance(result, dict)

    def test_get_retry_policy_state_corruption(self):
        """状态损坏重试策略"""
        policy = AdaptiveRetryPolicy()
        result = policy.get_retry_policy("state_corruption")
        assert isinstance(result, dict)

    def test_get_retry_policy_unknown(self):
        """未知失败类型"""
        policy = AdaptiveRetryPolicy()
        result = policy.get_retry_policy("unknown_error")
        assert isinstance(result, dict)


class TestStateMachineRepr:
    """测试 __repr__"""

    def test_repr(self):
        """__repr__ 应返回字符串"""
        sm = StateMachine()
        r = repr(sm)
        assert isinstance(r, str)
        assert "idle" in r.lower() or "IDLE" in r
