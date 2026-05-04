"""
人格算法包 — 7 种人格调节与学习算法
"""

from src.personality.algorithms import (
    # 贝叶斯推断
    BayesianConfig,
    BayesianUpdate,
    # 信息熵控制器
    EntropyConfig,
    EntropyController,
    FuzzyController,
    # 模糊控制
    FuzzyRule,
    # 卡尔曼滤波
    KalmanConfig,
    KalmanFilter1D,
    PersonalityFusionEngine,
    # 人格状态 & 融合引擎
    PersonalityState,
    # PID 控制器
    PIDConfig,
    PIDController,
    # 强化学习
    RLConfig,
    RLPersonalityAgent,
    UCB1Bandit,
    # 多臂老虎机
    UCB1Config,
)

__all__ = [
    # PID
    "PIDConfig",
    "PIDController",
    # Kalman
    "KalmanConfig",
    "KalmanFilter1D",
    # Fuzzy
    "FuzzyRule",
    "FuzzyController",
    # Personality
    "PersonalityState",
    "PersonalityFusionEngine",
    # Bayesian
    "BayesianConfig",
    "BayesianUpdate",
    # Entropy
    "EntropyConfig",
    "EntropyController",
    # UCB1
    "UCB1Config",
    "UCB1Bandit",
    # RL
    "RLConfig",
    "RLPersonalityAgent",
]
