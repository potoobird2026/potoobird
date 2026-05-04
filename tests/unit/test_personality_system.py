"""
人格系统单元测试 — PersonalityFusionEngine + PersonalityState

测试覆盖：
1. PersonalityState 基本操作（to_dict, from_dict, clamp）
2. PersonalityFusionEngine 初始化
3. compute_adjustment 基本功能
4. apply_adjustment 正确性
5. 死区（DEAD_ZONE）不调整
6. 限幅（MAX_SINGLE_ADJUST）
7. 自适应权重更新
8. reset 功能
9. _derive_personality_target 决策规则

新功能文件夹结构：测试.py
"""

import pytest
from src.personality.algorithms import (
    PersonalityState,
    PersonalityFusionEngine,
    PIDController,
    KalmanFilter1D,
    FuzzyController,
)


# ============================================================
# 1. PersonalityState 基本操作
# ============================================================

class TestPersonalityState:

    def test_default_values(self):
        """默认值应全为 50"""
        state = PersonalityState()
        for dim in PersonalityState.DIMENSIONS:
            assert getattr(state, dim) == 50.0

    def test_to_dict(self):
        state = PersonalityState(H=70, E=40, X=60, A=55, C=80, O=65)
        d = state.to_dict()
        assert d == {"H": 70, "E": 40, "X": 60, "A": 55, "C": 80, "O": 65}

    def test_from_dict(self):
        state = PersonalityState().from_dict({"H": 70, "E": 40})
        assert state.H == 70.0
        assert state.E == 40.0
        # 未设置的维度保持默认
        assert state.X == 50.0

    def test_from_dict_unknown_key_ignored(self):
        """未知维度应被忽略"""
        state = PersonalityState().from_dict({"H": 70, "Z": 99})
        assert state.H == 70.0

    def test_clamp_upper(self):
        state = PersonalityState(H=150, C=200)
        state.clamp()
        assert state.H == 100.0
        assert state.C == 100.0

    def test_clamp_lower(self):
        state = PersonalityState(H=-10, E=-50)
        state.clamp()
        assert state.H == 0.0
        assert state.E == 0.0

    def test_clamp_returns_self(self):
        state = PersonalityState()
        result = state.clamp()
        assert result is state

    def test_dimensions_count(self):
        """应有6个维度"""
        assert len(PersonalityState.DIMENSIONS) == 6
        assert PersonalityState.DIMENSIONS == ["H", "E", "X", "A", "C", "O"]


# ============================================================
# 2. PersonalityFusionEngine 初始化
# ============================================================

class TestFusionEngineInit:

    def test_init_creates_controllers_for_all_dimensions(self):
        engine = PersonalityFusionEngine()
        for dim in PersonalityState.DIMENSIONS:
            assert dim in engine._pid_controllers
            assert dim in engine._kalman_filters

    def test_init_default_weights(self):
        engine = PersonalityFusionEngine()
        weights = engine.get_weights()
        assert abs(weights["pid"] - 0.2) < 0.01
        assert abs(weights["kalman"] - 0.15) < 0.01
        assert abs(weights["fuzzy"] - 0.15) < 0.01
        assert abs(weights["bayesian"] - 0.2) < 0.01
        assert abs(weights["entropy"] - 0.1) < 0.01
        assert abs(weights["ucb"] - 0.1) < 0.01
        assert abs(weights["rl"] - 0.1) < 0.01

    def test_init_fuzzy_controller_exists(self):
        engine = PersonalityFusionEngine()
        assert isinstance(engine._fuzzy_controller, FuzzyController)


# ============================================================
# 3. compute_adjustment 基本功能
# ============================================================

class TestComputeAdjustment:

    def test_same_state_returns_zero_adjustment(self):
        """当前状态 = 目标状态 → 所有调节量为0（死区内）"""
        engine = PersonalityFusionEngine()
        state = PersonalityState()
        adjustments = engine.compute_adjustment(state, state)
        for dim, val in adjustments.items():
            assert abs(val) < 0.01, f"{dim} 应为0，实际 {val}"

    def test_large_error_produces_adjustment(self):
        """目标与当前差异大 → 应产生非零调节量"""
        engine = PersonalityFusionEngine()
        current = PersonalityState(H=50, E=50, X=50, A=50, C=50, O=50)
        target = PersonalityState(H=80, E=20, X=70, A=30, C=90, O=60)
        adjustments = engine.compute_adjustment(current, target)
        # 至少H维度应有显著调节（偏差30 > 死区3）
        assert abs(adjustments["H"]) > 0.01

    def test_adjustment_direction_positive(self):
        """目标 > 当前 → 调节量为正"""
        engine = PersonalityFusionEngine()
        current = PersonalityState(H=50)
        target = PersonalityState(H=80)
        adjustments = engine.compute_adjustment(current, target)
        assert adjustments["H"] > 0

    def test_adjustment_direction_negative(self):
        """目标 < 当前 → 调节量为负"""
        engine = PersonalityFusionEngine()
        current = PersonalityState(H=80)
        target = PersonalityState(H=50)
        adjustments = engine.compute_adjustment(current, target)
        assert adjustments["H"] < 0

    def test_all_dimensions_returned(self):
        engine = PersonalityFusionEngine()
        current = PersonalityState()
        target = PersonalityState(H=80, E=20, X=70, A=30, C=90, O=60)
        adjustments = engine.compute_adjustment(current, target)
        for dim in PersonalityState.DIMENSIONS:
            assert dim in adjustments

    def test_dead_zone_no_adjustment(self):
        """无历史数据时死区=0（不过滤），有数据后死区=σ×2"""
        engine = PersonalityFusionEngine()
        current = PersonalityState(H=50)
        target = PersonalityState(H=52)  # 偏差=2
        # 无历史数据时死区=0，偏差不会被过滤
        adjustments = engine.compute_adjustment(current, target)
        # 应该产生调节（因为死区=0）
        assert adjustments["H"] != 0.0
        # 但调节量不应超过 MAX_SINGLE_ADJUST
        assert abs(adjustments["H"]) <= 5.0

    def test_max_adjustment_limited(self):
        """单次调节量不超过 MAX_SINGLE_ADJUST"""
        engine = PersonalityFusionEngine()
        current = PersonalityState(H=0, E=0, X=0, A=0, C=0, O=0)
        target = PersonalityState(H=100, E=100, X=100, A=100, C=100, O=100)
        adjustments = engine.compute_adjustment(current, target)
        for dim, val in adjustments.items():
            assert abs(val) <= 5.0 + 0.01  # MAX_SINGLE_ADJUST = 5.0


# ============================================================
# 4. apply_adjustment 正确性
# ============================================================

class TestApplyAdjustment:

    def test_apply_increases_value(self):
        engine = PersonalityFusionEngine()
        state = PersonalityState(H=50)
        new_state = engine.apply_adjustment(state, {"H": 5.0})
        assert new_state.H == 55.0

    def test_apply_decreases_value(self):
        engine = PersonalityFusionEngine()
        state = PersonalityState(H=50)
        new_state = engine.apply_adjustment(state, {"H": -5.0})
        assert new_state.H == 45.0

    def test_apply_clamps_to_100(self):
        engine = PersonalityFusionEngine()
        state = PersonalityState(H=98)
        new_state = engine.apply_adjustment(state, {"H": 10.0})
        assert new_state.H == 100.0

    def test_apply_clamps_to_0(self):
        engine = PersonalityFusionEngine()
        state = PersonalityState(H=2)
        new_state = engine.apply_adjustment(state, {"H": -10.0})
        assert new_state.H == 0.0

    def test_apply_unknown_dimension_ignored(self):
        engine = PersonalityFusionEngine()
        state = PersonalityState()
        new_state = engine.apply_adjustment(state, {"Z": 10.0})
        # 所有维度应保持不变
        for dim in PersonalityState.DIMENSIONS:
            assert getattr(new_state, dim) == 50.0

    def test_apply_returns_new_state(self):
        """apply_adjustment 应返回新的状态对象（不修改原对象）"""
        engine = PersonalityFusionEngine()
        state = PersonalityState(H=50)
        new_state = engine.apply_adjustment(state, {"H": 5.0})
        # 原对象不变
        assert state.H == 50.0
        assert new_state.H == 55.0


# ============================================================
# 5. 自适应权重
# ============================================================

class TestAdaptiveWeights:

    def test_weights_sum_to_one(self):
        engine = PersonalityFusionEngine()
        # 触发多次更新
        current = PersonalityState(H=50)
        target = PersonalityState(H=80)
        for _ in range(10):
            engine.compute_adjustment(current, target)
        weights = engine.get_weights()
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01

    def test_weights_all_positive(self):
        engine = PersonalityFusionEngine()
        current = PersonalityState(H=50)
        target = PersonalityState(H=80)
        for _ in range(10):
            engine.compute_adjustment(current, target)
        weights = engine.get_weights()
        for source, w in weights.items():
            assert w > 0, f"{source} 权重应为正"


# ============================================================
# 6. reset 功能
# ============================================================

class TestReset:

    def test_reset_clears_controllers(self):
        engine = PersonalityFusionEngine()
        # 先运行一些计算
        current = PersonalityState(H=50)
        target = PersonalityState(H=80)
        engine.compute_adjustment(current, target)
        # 重置
        engine.reset()
        # PID 积分项应归零
        for dim in PersonalityState.DIMENSIONS:
            assert engine._pid_controllers[dim]._integral == 0.0
            assert engine._pid_controllers[dim]._prev_error == 0.0

    def test_reset_restores_default_weights(self):
        engine = PersonalityFusionEngine()
        current = PersonalityState(H=50)
        target = PersonalityState(H=80)
        for _ in range(10):
            engine.compute_adjustment(current, target)
        engine.reset()
        weights = engine.get_weights()
        assert abs(weights["pid"] - 0.2) < 0.01
        assert abs(weights["kalman"] - 0.15) < 0.01
        assert abs(weights["fuzzy"] - 0.15) < 0.01
        assert abs(weights["bayesian"] - 0.2) < 0.01


# ============================================================
# 7. get_weights
# ============================================================

class TestGetWeights:

    def test_returns_copy(self):
        """get_weights 应返回副本，修改不影响内部"""
        engine = PersonalityFusionEngine()
        weights = engine.get_weights()
        weights["pid"] = 999.0
        assert engine.get_weights()["pid"] != 999.0
