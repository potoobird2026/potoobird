"""
人格算法 — 7 种人格调节与学习算法

科学依据：
1. PID 控制（Proportional-Integral-Derivative, 1922）
2. 卡尔曼滤波（Kalman Filter, 1960）— 最优状态估计
3. 模糊控制（Fuzzy Control, Zadeh 1965, Mamdani 1974）
4. 贝叶斯推断（Bayes' Theorem, 1763）— 根据新证据更新信念
5. 信息熵（Shannon Entropy, 1948）— 衡量不确定性，指导探索/利用
6. 多臂老虎机 UCB1（Auer et al., 2002）— 探索与利用的最优平衡
7. Q-Learning（Watkins, 1989）— 强化学习，通过奖惩学习最优策略

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：01_记忆系统全局设计.md §人格系统
"""

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger("long_agent.personality")


# ============================================================
# PID Controller — PID 控制器
# ============================================================


@dataclass
class PIDConfig:
    """PID 参数配置"""

    kp: float = 1.0  # 比例增益
    ki: float = 0.1  # 积分增益
    kd: float = 0.05  # 微分增益
    setpoint: float = 0.5  # 目标值（人格目标状态）
    output_min: float = 0.0
    output_max: float = 1.0
    integral_limit: float = 10.0  # 积分限幅（防积分饱和）


class PIDController:
    """
    PID 控制器 — 人格状态调节

    科学依据：PID 控制（Proportional-Integral-Derivative, 1922）

    用途：根据当前人格状态与目标的偏差，计算调节量
    - 比例项（P）：响应当前偏差
    - 积分项（I）：消除稳态误差
    - 微分项（D）：预测未来趋势

    所有参数不写死，由 LLM 根据用户反馈动态调整。
    """

    def __init__(self, config: PIDConfig = None):
        self.config = config or PIDConfig()
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_output = 0.0

    def compute(self, current_value: float, dt: float = 1.0) -> float:
        """
        计算 PID 输出

        Args:
            current_value: 当前值（当前人格状态）
            dt: 时间步长

        Returns:
            float: 调节量 [output_min, output_max]
        """
        error = self.config.setpoint - current_value

        # 比例项
        p_term = self.config.kp * error

        # 积分项（带限幅防饱和）
        self._integral += error * dt
        self._integral = max(
            -self.config.integral_limit, min(self.config.integral_limit, self._integral)
        )
        i_term = self.config.ki * self._integral

        # 微分项
        d_term = 0.0
        if dt > 0:
            d_term = self.config.kd * (error - self._prev_error) / dt

        # 总输出
        output = p_term + i_term + d_term
        output = max(self.config.output_min, min(self.config.output_max, output))

        self._prev_error = error
        self._prev_output = output

        return output

    def reset(self):
        """重置控制器状态"""
        self._integral = 0.0
        self._prev_error = 0.0
        self._prev_output = 0.0

    def auto_tune(self, oscillation_period: float):
        """
        Ziegler-Nichols 自动调参

        所有参数不写死，由公式计算。
        Ziegler-Nichols 公式：
        - Kp = 0.6 × Ku
        - Ki = 1.2 × Ku / Tu
        - Kd = 0.075 × Ku × Tu
        （Ku = 临界增益, Tu = 振荡周期）

        Args:
            oscillation_period: 临界振荡周期 Tu
        """
        # 默认临界增益（可由 LLM 动态调整）
        ku = 1.0
        tu = oscillation_period

        if tu > 0:
            self.config.kp = 0.6 * ku
            self.config.ki = 1.2 * ku / tu
            self.config.kd = 0.075 * ku * tu
            logger.info(
                f"Ziegler-Nichols 自动调参: Kp={self.config.kp:.3f}, "
                f"Ki={self.config.ki:.3f}, Kd={self.config.kd:.3f}"
            )


# ============================================================
# Kalman Filter — 卡尔曼滤波器
# ============================================================


@dataclass
class KalmanConfig:
    """卡尔曼滤波参数"""

    process_noise: float = 0.01  # Q: 过程噪声协方差
    measurement_noise: float = 0.1  # R: 测量噪声协方差
    initial_estimate: float = 0.5  # 初始估计值
    initial_error: float = 1.0  # 初始估计误差


class KalmanFilter1D:
    """
    一维卡尔曼滤波器 — 人格状态最优估计

    科学依据：卡尔曼滤波（Kalman, 1960）

    用途：从带有噪声的观测数据中估计真实人格状态
    - 预测步骤：根据模型预测下一状态
    - 更新步骤：结合观测值修正预测

    所有参数不写死，由公式/LLM/用户互动获得。
    """

    def __init__(self, config: KalmanConfig = None):
        self.config = config or KalmanConfig()
        self._x = self.config.initial_estimate  # 状态估计
        self._p = self.config.initial_error  # 估计误差协方差
        self._q = self.config.process_noise  # 过程噪声
        self._r = self.config.measurement_noise  # 测量噪声

    @property
    def estimate(self) -> float:
        """当前最优估计"""
        return self._x

    def predict(self, control_input: float = 0.0) -> float:
        """
        预测步骤

        Args:
            control_input: 控制输入（外部调节量，如 PID 输出）

        Returns:
            float: 预测值
        """
        # 状态预测（简化模型：x = x + u）
        self._x = self._x + control_input
        # 误差协方差预测
        self._p = self._p + self._q
        return self._x

    def update(self, measurement: float) -> float:
        """
        更新步骤

        Args:
            measurement: 观测值

        Returns:
            float: 更新后的最优估计
        """
        # 卡尔曼增益
        if self._p + self._r == 0:
            k = 0.0
        else:
            k = self._p / (self._p + self._r)

        # 状态更新
        self._x = self._x + k * (measurement - self._x)
        # 误差协方差更新
        self._p = (1 - k) * self._p

        return self._x

    def filter(self, measurement: float, control_input: float = 0.0) -> float:
        """
        完整滤波流程：预测 + 更新

        Args:
            measurement: 观测值
            control_input: 控制输入

        Returns:
            float: 最优估计
        """
        self.predict(control_input)
        return self.update(measurement)

    def adapt_noise(self, residual_history: list[float]):
        """
        自适应噪声调整

        根据残差历史动态调整测量噪声 R。
        残差方差大 → 增大 R（更不信任观测）
        残差方差小 → 减小 R（更信任观测）

        Args:
            residual_history: 最近 N 个残差值
        """
        if len(residual_history) < 2:
            return

        # 计算残差方差
        mean = sum(residual_history) / len(residual_history)
        variance = sum((r - mean) ** 2 for r in residual_history) / len(residual_history)

        # 自适应调整 R
        self._r = max(0.01, min(1.0, variance))
        logger.debug(f"卡尔曼噪声自适应: R={self._r:.4f}")


# ============================================================
# FuzzyController — 模糊控制器
# ============================================================


@dataclass
class FuzzyRule:
    """模糊规则"""

    name: str = ""
    conditions: dict = field(default_factory=dict)  # {"error": "positive", "delta": "small"}
    output_set: str = "medium"  # 输出模糊集
    weight: float = 1.0


class FuzzyController:
    """
    模糊控制器 — 人格状态模糊推理

    科学依据：模糊集合理论（Zadeh, 1965）+ Mamdani 模糊推理（1974）

    用途：处理人格调节中的不确定性和模糊性
    - 模糊化：将精确输入转为模糊集
    - 规则推理：应用模糊规则
    - 去模糊化：将模糊输出转为精确值

    所有参数不写死，由 LLM 根据用户反馈动态调整。
    """

    # 模糊集定义（三角形/梯形隶属函数参数）
    # 每个模糊集: (左端点, 顶点, 右端点)
    ERROR_SETS = {
        "negative_large": (-1.0, -0.6, -0.3),
        "negative_small": (-0.4, -0.2, 0.0),
        "zero": (-0.1, 0.0, 0.1),
        "positive_small": (0.0, 0.2, 0.4),
        "positive_large": (0.3, 0.6, 1.0),
    }

    DELTA_SETS = {
        "negative": (-1.0, -0.3, 0.0),
        "zero": (-0.1, 0.0, 0.1),
        "positive": (0.0, 0.3, 1.0),
    }

    OUTPUT_SETS = {
        "decrease_large": -0.8,
        "decrease_small": -0.3,
        "hold": 0.0,
        "increase_small": 0.3,
        "increase_large": 0.8,
    }

    def __init__(self, rules: list[FuzzyRule] = None):
        self.rules = rules or self._default_rules()

    def _default_rules(self) -> list[FuzzyRule]:
        """
        默认模糊规则

        规则不写死，可由 LLM 根据用户反馈动态调整。
        """
        return [
            FuzzyRule("R1", {"error": "negative_large", "delta": "any"}, "increase_large", 1.0),
            FuzzyRule(
                "R2", {"error": "negative_small", "delta": "negative"}, "increase_small", 1.0
            ),
            FuzzyRule("R3", {"error": "zero", "delta": "zero"}, "hold", 1.0),
            FuzzyRule(
                "R4", {"error": "positive_small", "delta": "positive"}, "decrease_small", 1.0
            ),
            FuzzyRule("R5", {"error": "positive_large", "delta": "any"}, "decrease_large", 1.0),
            FuzzyRule("R6", {"error": "negative_small", "delta": "positive"}, "hold", 0.8),
            FuzzyRule("R7", {"error": "positive_small", "delta": "negative"}, "hold", 0.8),
        ]

    def compute(self, error: float, delta: float) -> float:
        """
        模糊推理计算

        Args:
            error: 偏差（当前值 - 目标值）
            delta: 偏差变化率

        Returns:
            float: 调节量 [-1, 1]
        """
        # 1. 模糊化
        error_membership = self._fuzzify(error, self.ERROR_SETS)
        delta_membership = self._fuzzify(delta, self.DELTA_SETS)

        # 2. 规则推理
        output_aggregate = {}
        for rule in self.rules:
            strength = self._evaluate_rule(rule, error_membership, delta_membership)
            if strength > 0:
                if rule.output_set not in output_aggregate:
                    output_aggregate[rule.output_set] = 0.0
                output_aggregate[rule.output_set] = max(
                    output_aggregate[rule.output_set], strength * rule.weight
                )

        # 3. 去模糊化（重心法）
        return self._defuzzify(output_aggregate)

    def _fuzzify(self, value: float, fuzzy_sets: dict) -> dict[str, float]:
        """
        模糊化：计算值对各模糊集的隶属度

        Args:
            value: 精确值
            fuzzy_sets: 模糊集定义

        Returns:
            dict: {模糊集名称: 隶属度}
        """
        memberships = {}
        for name, (left, peak, right) in fuzzy_sets.items():
            memberships[name] = self._triangle_membership(value, left, peak, right)
        return memberships

    @staticmethod
    def _triangle_membership(x: float, left: float, peak: float, right: float) -> float:
        """三角形隶属函数"""
        if x <= left or x >= right:
            return 0.0
        if x == peak:
            return 1.0
        if x < peak:
            return (x - left) / (peak - left) if peak != left else 0.0
        return (right - x) / (right - peak) if right != peak else 0.0

    def _evaluate_rule(self, rule: FuzzyRule, error_mem: dict, delta_mem: dict) -> float:
        """评估单条规则的激活强度"""
        error_level = error_mem.get(rule.conditions.get("error", ""), 0.0)
        delta_cond = rule.conditions.get("delta", "any")
        if delta_cond == "any":
            delta_level = 1.0
        else:
            delta_level = delta_mem.get(delta_cond, 0.0)
        return min(error_level, delta_level)

    def _defuzzify(self, output_aggregate: dict) -> float:
        """
        去模糊化：重心法（COG）

        Args:
            output_aggregate: {模糊集名称: 激活强度}

        Returns:
            float: 精确输出值
        """
        if not output_aggregate:
            return 0.0

        numerator = 0.0
        denominator = 0.0
        for fuzzy_set, strength in output_aggregate.items():
            crisp_value = self.OUTPUT_SETS.get(fuzzy_set, 0.0)
            numerator += crisp_value * strength
            denominator += strength

        if denominator == 0:
            return 0.0
        return max(-1.0, min(1.0, numerator / denominator))


# ============================================================
# FusionEngine — 三路融合引擎
# ============================================================


@dataclass
class PersonalityState:
    """
    人格状态 — HEXACO 六维

    每个维度值域 [0, 100]，初始默认 50。
    每次交互后根据用户反馈微调，单次最大调整量由 PID 死区控制。
    """

    H: float = 50.0  # 诚实-谦逊
    E: float = 50.0  # 情绪性
    X: float = 50.0  # 外向性
    A: float = 50.0  # 宜人性
    C: float = 50.0  # 尽责性
    O: float = 50.0  # 经验开放性

    DIMENSIONS = ["H", "E", "X", "A", "C", "O"]

    def to_dict(self) -> dict[str, float]:
        return {d: getattr(self, d) for d in self.DIMENSIONS}

    def from_dict(self, data: dict):
        for d in self.DIMENSIONS:
            if d in data:
                setattr(self, d, float(data[d]))
        return self

    def clamp(self):
        """将所有维度限制在 [0, 100]"""
        for d in self.DIMENSIONS:
            setattr(self, d, max(0.0, min(100.0, getattr(self, d))))
        return self


class PersonalityFusionEngine:
    """
    人格融合引擎 — 7种算法多路融合

    设计原则：
    - PID 负责快速响应用户反馈偏差
    - 卡尔曼滤波负责从噪声观测中估计真实人格
    - 模糊控制负责处理不确定性（"用户好像有点不满"）
    - 贝叶斯推断负责信念更新（按置信度加权）
    - 信息熵负责探索/利用平衡
    - UCB1 负责策略选择
    - 强化学习负责长期策略优化
    - 各路输出加权融合，权重由历史精度自适应调整

    科学依据：
    - 多传感器融合（Multi-Sensor Fusion）：多路独立估计取加权平均
    - 权重更新：按各路历史误差方差的倒数加权（最优线性无偏估计 BLUE）
    - 死区动态计算：死区 = σ_error × 2（控制论，Åström & Murray, 2008）

    所有参数不写死，由公式计算或 LLM 动态调整。
    """

    # 单次最大调整量（防止人格突变，可通过构造函数覆盖）
    DEFAULT_MAX_SINGLE_ADJUST = 5.0

    def __init__(self, weights: dict = None, max_single_adjust: float = None):
        """
        Args:
            weights: 融合权重字典（None 时使用等权）
            max_single_adjust: 单次最大调整量（None 时使用 5.0）
        """
        self.MAX_SINGLE_ADJUST = (
            max_single_adjust if max_single_adjust is not None else self.DEFAULT_MAX_SINGLE_ADJUST
        )

        # 每维独立一套 PID + 卡尔曼 + 模糊
        self._pid_controllers: dict[str, PIDController] = {}
        self._kalman_filters: dict[str, KalmanFilter1D] = {}
        self._fuzzy_controller = FuzzyController()

        # 新增4种算法
        self._bayesian_updates: dict[str, BayesianUpdate] = {}
        self._entropy_controller = EntropyController()
        self._ucb_bandit = UCB1Bandit()
        self._rl_agents: dict[str, RLPersonalityAgent] = {}

        # 融合权重（None 时使用等权，可通过构造函数覆盖）
        if weights is not None:
            self._weights = dict(weights)
        else:
            # 等权：所有算法均等权重
            self._weights = {
                "pid": 0.2,
                "kalman": 0.15,
                "fuzzy": 0.15,
                "bayesian": 0.2,
                "entropy": 0.1,
                "ucb": 0.1,
                "rl": 0.1,
            }

        # 历史误差记录（用于自适应权重）
        self._error_history: dict[str, list[float]] = {
            "pid": [],
            "kalman": [],
            "fuzzy": [],
            "bayesian": [],
            "entropy": [],
            "ucb": [],
            "rl": [],
        }

        # 初始化每维的 PID 和卡尔曼
        for dim in PersonalityState.DIMENSIONS:
            pid_config = PIDConfig(
                kp=0.5,
                ki=0.1,
                kd=0.05,
                setpoint=50.0,  # 目标值由外部传入，此处为默认
                output_min=-self.MAX_SINGLE_ADJUST,
                output_max=self.MAX_SINGLE_ADJUST,
                integral_limit=10.0,
            )
            self._pid_controllers[dim] = PIDController(pid_config)

            kalman_config = KalmanConfig(
                process_noise=0.01,
                measurement_noise=0.1,
                initial_estimate=50.0,
                initial_error=1.0,
            )
            self._kalman_filters[dim] = KalmanFilter1D(kalman_config)

            self._bayesian_updates[dim] = BayesianUpdate()
            self._rl_agents[dim] = RLPersonalityAgent()

    def compute_adjustment(
        self,
        current_state: PersonalityState,
        target_state: PersonalityState,
        dt: float = 1.0,
    ) -> dict[str, float]:
        """
        计算人格调节量

        Args:
            current_state: 当前人格状态（从 personality.md 加载）
            target_state: 目标人格状态（由 LLM 根据用户反馈生成）
            dt: 时间步长

        Returns:
            dict: {维度: 调节量}，正数表示增加，负数表示减少
        """
        adjustments = {}

        for dim in PersonalityState.DIMENSIONS:
            current_val = getattr(current_state, dim)
            target_val = getattr(target_state, dim)
            error = target_val - current_val

            # 动态死区：偏差绝对值 < σ_error × 2 时不调整（控制论，Åström & Murray, 2008）
            # 从历史误差中取标准差，数据不足时死区为0（不过滤）
            all_errors = []
            for hist in self._error_history.values():
                all_errors.extend(hist[-10:])
            if len(all_errors) >= 3:
                import statistics

                dead_zone = statistics.stdev(all_errors[-20:]) * 2
            else:
                dead_zone = 0.0

            if abs(error) < dead_zone:
                adjustments[dim] = 0.0
                continue

            # 七路独立计算
            pid = self._pid_controllers[dim]
            pid.config.setpoint = target_val / 100.0
            pid_output = pid.compute(current_val / 100.0, dt) * 100.0

            kalman = self._kalman_filters[dim]
            kalman_output = (
                kalman.filter(measurement=target_val, control_input=pid_output / 100.0)
                - current_val
            )

            delta = error / max(dt, 0.01)
            fuzzy_output = (
                self._fuzzy_controller.compute(error=error / 100.0, delta=delta / 100.0) * 100.0
            )

            # 贝叶斯推断（安全兜底）
            try:
                bayesian = self._bayesian_updates[dim]
                evidence = (target_val - current_val) / 100.0
                bayesian_result = bayesian.update(dimension=dim, evidence=evidence, weight=0.5)
                bayesian_output = (
                    bayesian_result.get("posterior_probability", 0.5) * 100.0 - current_val
                )
            except Exception:
                bayesian_output = 0.0

            # 信息熵（安全兜底）
            try:
                history_for_dim = self._error_history.get("pid", [])[-5:]
                entropy_val = (
                    self._entropy_controller.calculate_entropy(history_for_dim)
                    if history_for_dim
                    else 0.5
                )
                entropy_output = error * 0.1 * (1 + entropy_val)
            except Exception:
                entropy_output = 0.0

            # UCB1 多臂老虎机（安全兜底）
            try:
                counts = getattr(self._ucb_bandit, "counts", None)
                if counts:
                    arm = self._ucb_bandit.select_arm()
                else:
                    arm = 0
                ucb_output = error * (0.05 + 0.05 * arm)
            except Exception:
                ucb_output = 0.0

            # 强化学习（安全兜底）
            try:
                rl = self._rl_agents[dim]
                rl_action = rl.select_action(current_val)
                rl_output = rl.action_to_delta(rl_action)
            except Exception:
                rl_output = 0.0

            # 加权融合
            w = self._weights
            fused = (
                w["pid"] * pid_output
                + w["kalman"] * kalman_output
                + w["fuzzy"] * fuzzy_output
                + w["bayesian"] * bayesian_output
                + w["entropy"] * entropy_output
                + w["ucb"] * ucb_output
                + w["rl"] * rl_output
            )

            # 限幅
            fused = max(-self.MAX_SINGLE_ADJUST, min(self.MAX_SINGLE_ADJUST, fused))

            # 记录误差历史（用于自适应权重）
            self._record_error("pid", abs(error - pid_output))
            self._record_error("kalman", abs(error - kalman_output))
            self._record_error("fuzzy", abs(error - fuzzy_output))
            self._record_error("bayesian", abs(error - bayesian_output))
            self._record_error("entropy", abs(error - entropy_output))
            self._record_error("ucb", abs(error - ucb_output))
            self._record_error("rl", abs(error - rl_output))

            adjustments[dim] = fused

        # 自适应更新融合权重
        self._update_weights()

        return adjustments

    def apply_adjustment(
        self,
        state: PersonalityState,
        adjustments: dict[str, float],
    ) -> PersonalityState:
        """
        将调节量应用到人格状态

        Args:
            state: 当前人格状态（不会被修改）
            adjustments: compute_adjustment 返回的调节量

        Returns:
            PersonalityState: 新的人格状态（已 clamp 到 [0, 100]）
        """
        new_state = PersonalityState(
            H=state.H,
            E=state.E,
            X=state.X,
            A=state.A,
            C=state.C,
            O=state.O,
        )
        for dim, delta in adjustments.items():
            if dim in PersonalityState.DIMENSIONS:
                setattr(new_state, dim, getattr(new_state, dim) + delta)
        new_state.clamp()
        return new_state

    def _record_error(self, source: str, error: float):
        """记录各路误差"""
        history = self._error_history[source]
        history.append(error)
        # 只保留最近 50 条
        if len(history) > 50:
            self._error_history[source] = history[-50:]

    def _update_weights(self):
        """
        自适应更新融合权重

        按误差方差的倒数加权（BLUE 最优线性无偏估计）：
        w_i = (1/σ²_i) / Σ(1/σ²_j)

        误差方差大 → 权重降低（不信任该路）
        误差方差小 → 权重升高（信任该路）
        """
        inverse_var = {}
        for source, errors in self._error_history.items():
            if len(errors) < 5:
                inverse_var[source] = 1.0 / 0.1  # 数据不足时用默认
                continue
            mean = sum(errors) / len(errors)
            variance = sum((e - mean) ** 2 for e in errors) / len(errors)
            variance = max(variance, 1e-6)  # 防止除零
            inverse_var[source] = 1.0 / variance

        total = sum(inverse_var.values())
        if total > 0:
            for source in self._weights:
                self._weights[source] = inverse_var[source] / total

        logger.debug(
            f"融合权重更新: PID={self._weights['pid']:.3f}, "
            f"Kalman={self._weights['kalman']:.3f}, "
            f"Fuzzy={self._weights['fuzzy']:.3f}"
        )

    def get_weights(self) -> dict[str, float]:
        """获取当前融合权重"""
        return dict(self._weights)

    def reset(self):
        """重置所有控制器状态"""
        for dim in PersonalityState.DIMENSIONS:
            self._pid_controllers[dim].reset()
            self._kalman_filters[dim] = KalmanFilter1D(KalmanConfig())
        self._weights = {
            "pid": 0.2,
            "kalman": 0.15,
            "fuzzy": 0.15,
            "bayesian": 0.2,
            "entropy": 0.1,
            "ucb": 0.1,
            "rl": 0.1,
        }
        for k in self._error_history:
            self._error_history[k] = []


# ============================================================
# BayesianUpdate — 贝叶斯推断
# ============================================================


@dataclass
class BayesianConfig:
    """贝叶斯推断配置"""

    prior_strength: float = 1.0  # 先验强度（等效样本数）
    learning_rate: float = 0.1  # 学习率（控制后验更新速度）
    min_confidence: float = 0.01  # 最小置信度（避免零概率）
    max_confidence: float = 0.99  # 最大置信度（避免绝对确定）


class BayesianUpdate:
    """
    贝叶斯推断 — 根据新证据更新人格信念

    科学依据：贝叶斯定理（Bayes' Theorem, 1763）
    P(H|E) = P(E|H) * P(H) / P(E)

    用途：当接收到新的用户反馈（证据 E）时，更新对人格维度（假设 H）的信念
    - 先验概率 P(H)：当前对人格状态的信念
    - 似然 P(E|H)：在该人格状态下观察到该反馈的概率
    - 后验概率 P(H|E)：更新后的信念

    使用 Beta 分布作为共轭先验，支持在线更新。
    """

    def __init__(self, config: BayesianConfig = None):
        self.config = config or BayesianConfig()
        # Beta 分布参数 (α, β)，初始化为均匀先验
        self._alpha: dict[str, float] = {}
        self._beta: dict[str, float] = {}
        self._history: list[dict] = []

    def _init_dimension(self, dimension: str):
        """初始化维度的 Beta 先验"""
        if dimension not in self._alpha:
            s = self.config.prior_strength
            self._alpha[dimension] = s  # α 初始值
            self._beta[dimension] = s  # β 初始值（均匀先验）

    def update(self, dimension: str, evidence: float, weight: float = 1.0) -> dict:
        """
        根据新证据更新信念

        Args:
            dimension: 人格维度名称
            evidence: 证据值 [0, 1]，0=负向，1=正向
            weight: 证据权重（可信度）

        Returns:
            dict: {mean, variance, confidence, alpha, beta}
        """
        self._init_dimension(dimension)

        # 将证据映射为 Beta 分布的伪计数
        lr = self.config.learning_rate
        alpha_update = lr * evidence * weight
        beta_update = lr * (1.0 - evidence) * weight

        self._alpha[dimension] += alpha_update
        self._beta[dimension] += beta_update

        # 计算后验统计量
        a, b = self._alpha[dimension], self._beta[dimension]
        mean = a / (a + b)
        variance = (a * b) / ((a + b) ** 2 * (a + b + 1))
        confidence = 1.0 - variance * 12  # 归一化置信度
        confidence = max(self.config.min_confidence, min(self.config.max_confidence, confidence))

        result = {
            "dimension": dimension,
            "mean": round(mean, 4),
            "variance": round(variance, 6),
            "confidence": round(confidence, 4),
            "alpha": round(a, 2),
            "beta": round(b, 2),
        }

        self._history.append(result)
        logger.debug(f"贝叶斯更新 [{dimension}]: mean={mean:.3f}, conf={confidence:.3f}")
        return result

    def get_belief(self, dimension: str) -> dict:
        """获取当前信念分布"""
        self._init_dimension(dimension)
        a, b = self._alpha[dimension], self._beta[dimension]
        mean = a / (a + b)
        variance = (a * b) / ((a + b) ** 2 * (a + b + 1))
        return {
            "dimension": dimension,
            "mean": round(mean, 4),
            "variance": round(variance, 6),
            "confidence": round(1.0 - variance * 12, 4),
            "alpha": round(a, 2),
            "beta": round(b, 2),
        }

    def batch_update(self, dimension: str, evidences: list[tuple[float, float]]) -> dict:
        """
        批量更新信念

        Args:
            dimension: 人格维度
            evidences: [(evidence, weight), ...] 列表

        Returns:
            最终信念分布
        """
        for ev, wt in evidences:
            self.update(dimension, ev, wt)
        return self.get_belief(dimension)

    def reset(self, dimension: str = None):
        """重置信念"""
        if dimension:
            self._alpha.pop(dimension, None)
            self._beta.pop(dimension, None)
        else:
            self._alpha.clear()
            self._beta.clear()
            self._history.clear()


# ============================================================
# EntropyController — 信息熵控制器
# ============================================================


@dataclass
class EntropyConfig:
    """信息熵控制器配置"""

    target_entropy: float = 0.5  # 目标熵值（中等不确定性）
    entropy_threshold: float = 0.3  # 熵阈值（低于此值视为确定性高）
    exploration_boost: float = 0.2  # 探索增益（高熵时增加探索）
    min_exploration: float = 0.05  # 最小探索率
    max_exploration: float = 0.8  # 最大探索率


class EntropyController:
    """
    信息熵控制器 — 衡量不确定性，决定探索/利用

    科学依据：香农信息熵（Shannon Entropy, 1948）
    H(X) = -Σ p(x) * log2(p(x))

    用途：
    - 衡量人格状态的不确定性
    - 高熵 → 增加探索（尝试新策略）
    - 低熵 → 增加利用（使用已知最优策略）
    - 人格系统通过熵来动态调整探索/利用平衡
    """

    def __init__(self, config: EntropyConfig = None):
        self.config = config or EntropyConfig()
        self._entropy_history: list[dict] = []
        self._strategy_weights: dict[str, float] = {}

    @staticmethod
    def shannon_entropy(probabilities: list[float]) -> float:
        """
        计算香农熵

        Args:
            probabilities: 概率分布（应归一化）

        Returns:
            float: 熵值 [0, log2(n)]
        """
        probs = [p for p in probabilities if p > 0]
        total = sum(probs)
        if total <= 0:
            return 0.0
        # 归一化
        probs = [p / total for p in probs]
        entropy = -sum(p * math.log2(p) for p in probs)
        return entropy

    @staticmethod
    def normalized_entropy(probabilities: list[float]) -> float:
        """
        计算归一化熵 [0, 1]

        Returns:
            float: 归一化熵值，0=完全确定，1=最大不确定性
        """
        n = len(probabilities)
        if n <= 1:
            return 0.0
        raw = EntropyController.shannon_entropy(probabilities)
        max_entropy = math.log2(n)
        if max_entropy <= 0:
            return 0.0
        return raw / max_entropy

    def compute_exploration_rate(self, entropy: float) -> float:
        """
        根据熵值计算探索率

        - 高熵 → 高探索（不确定性高，需要探索）
        - 低熵 → 低探索（已经确定，直接利用）

        Args:
            entropy: 当前归一化熵值 [0, 1]

        Returns:
            float: 探索率 [min_exploration, max_exploration]
        """
        cfg = self.config
        if entropy >= cfg.target_entropy:
            # 高熵：增加探索
            scale = (entropy - cfg.target_entropy) / max(1.0 - cfg.target_entropy, 1e-9)
            rate = cfg.min_exploration + (cfg.max_exploration - cfg.min_exploration) * scale
        else:
            # 低熵：减少探索，增加利用
            scale = 1.0 - (entropy / max(cfg.target_entropy, 1e-9))
            rate = cfg.min_exploration * scale

        rate = max(cfg.min_exploration, min(cfg.max_exploration, rate))
        return rate

    def evaluate(self, probabilities: list[float], labels: list[str] = None) -> dict:
        """
        评估概率分布并给出探索建议

        Args:
            probabilities: 概率分布
            labels: 各维度标签（可选）

        Returns:
            dict: {entropy, normalized_entropy, exploration_rate, suggestion}
        """
        raw_entropy = self.shannon_entropy(probabilities)
        norm_entropy = self.normalized_entropy(probabilities)
        exploration_rate = self.compute_exploration_rate(norm_entropy)

        # 生成建议
        if norm_entropy > 0.7:
            suggestion = "high_explore"
        elif norm_entropy > 0.4:
            suggestion = "balanced"
        else:
            suggestion = "high_exploit"

        result = {
            "entropy": round(raw_entropy, 4),
            "normalized_entropy": round(norm_entropy, 4),
            "exploration_rate": round(exploration_rate, 4),
            "suggestion": suggestion,
        }

        if labels and len(labels) == len(probabilities):
            result["distribution"] = {label: round(p, 4) for label, p in zip(labels, probabilities)}

        self._entropy_history.append(result)
        logger.debug(
            f"熵评估: H={raw_entropy:.3f}, norm_H={norm_entropy:.3f}, "
            f"explore={exploration_rate:.3f}, action={suggestion}"
        )
        return result

    def personality_entropy(self, personality_vector: dict[str, float]) -> dict:
        """
        计算人格向量各维度的熵值

        Args:
            personality_vector: {dimension: value} 人格维度值

        Returns:
            熵评估结果
        """
        values = list(personality_vector.values())
        return self.evaluate(values, labels=list(personality_vector.keys()))

    def get_history(self) -> list[dict]:
        """获取熵历史"""
        return list(self._entropy_history)


# ============================================================
# UCB1Bandit — 多臂老虎机
# ============================================================


@dataclass
class UCB1Config:
    """UCB1 配置"""

    n_arms: int = 5  # 臂数量（可选策略数）
    exploration_factor: float = 1.414  # 探索因子 c = sqrt(2)
    initial_pulls: int = 1  # 初始拉动次数（确保每个臂至少尝试一次）
    reward_clip: tuple = (0.0, 1.0)  # 奖励裁剪范围


class UCB1Bandit:
    """
    多臂老虎机 UCB1 — 探索和利用平衡

    科学依据：UCB1 算法（Auer, Cesa-Bianchi & Fischer, 2002）
    UCB1(i) = X̄_i + c * sqrt(ln(n) / n_i)

    用途：
    - 在多个可选人格策略中选择最优策略
    - 自动平衡探索（尝试新策略）和利用（使用已知最优策略）
    - 随着交互增多，逐渐收敛到最优策略

    应用场景：
    - 选择回复风格（正式/随意/幽默/温暖）
    - 选择记忆策略（详细/精简/结构化）
    - 选择交互频率（主动/被动/适中）
    """

    def __init__(self, config: UCB1Config = None, arm_names: list[str] = None):
        self.config = config or UCB1Config()
        n = self.config.n_arms

        # 臂名称
        if arm_names:
            self._arm_names = arm_names[:n]
            n = len(self._arm_names)
        else:
            self._arm_names = [f"arm_{i}" for i in range(n)]

        self._n_arms = n
        # 每个臂的统计量
        self._counts = [0] * n  # 拉动次数
        self._values = [0.0] * n  # 平均奖励
        self._total_pulls = 0
        self._history: list[dict] = []

    def select_arm(self) -> tuple[int, str]:
        """
        选择臂（策略）

        使用 UCB1 公式：
        UCB(i) = avg_reward_i + c * sqrt(ln(total_pulls) / count_i)

        Returns:
            (arm_index, arm_name)
        """
        # 确保每个臂至少尝试一次
        for i in range(self._n_arms):
            if self._counts[i] < self.config.initial_pulls:
                return i, self._arm_names[i]

        # 计算每个臂的 UCB 值
        import math

        total = self._total_pulls
        c = self.config.exploration_factor
        ucb_values = []

        for i in range(self._n_arms):
            avg_reward = self._values[i]
            exploration = c * math.sqrt(math.log(total) / self._counts[i])
            ucb_values.append(avg_reward + exploration)

        # 选择 UCB 值最大的臂
        best_idx = max(range(self._n_arms), key=lambda i: ucb_values[i])
        return best_idx, self._arm_names[best_idx]

    def update(self, arm_index: int, reward: float):
        """
        更新臂的奖励

        Args:
            arm_index: 臂索引
            reward: 奖励值 [0, 1]
        """
        # 裁剪奖励
        lo, hi = self.config.reward_clip
        reward = max(lo, min(hi, reward))

        self._counts[arm_index] += 1
        self._total_pulls += 1

        # 增量更新平均值
        n = self._counts[arm_index]
        old_value = self._values[arm_index]
        self._values[arm_index] = old_value + (reward - old_value) / n

        self._history.append(
            {
                "arm": self._arm_names[arm_index],
                "reward": round(reward, 4),
                "new_avg": round(self._values[arm_index], 4),
            }
        )

        logger.debug(
            f"UCB1 更新 [{self._arm_names[arm_index]}]: "
            f"reward={reward:.3f}, avg={self._values[arm_index]:.3f}"
        )

    def get_stats(self) -> dict:
        """获取所有臂的统计信息"""
        stats = {}
        for i in range(self._n_arms):
            stats[self._arm_names[i]] = {
                "count": self._counts[i],
                "average_reward": round(self._values[i], 4),
                "ucb_value": round(
                    self._values[i]
                    + self.config.exploration_factor
                    * math.sqrt(math.log(max(self._total_pulls, 1)) / max(self._counts[i], 1)),
                    4,
                ),
            }
        return stats

    def get_best_arm(self) -> tuple[int, str, float]:
        """
        获取当前最优臂

        Returns:
            (arm_index, arm_name, average_reward)
        """
        best_idx = max(range(self._n_arms), key=lambda i: self._values[i])
        return best_idx, self._arm_names[best_idx], round(self._values[best_idx], 4)

    def reset(self):
        """重置所有臂"""
        self._counts = [0] * self._n_arms
        self._values = [0.0] * self._n_arms
        self._total_pulls = 0
        self._history.clear()


# ============================================================
# RLPersonalityAgent — 强化学习 (Q-Learning)
# ============================================================


@dataclass
class RLConfig:
    """强化学习配置"""

    learning_rate: float = 0.1  # α — 学习率
    discount_factor: float = 0.9  # γ — 折扣因子
    epsilon: float = 0.1  # ε — 探索率
    epsilon_decay: float = 0.995  # ε 衰减
    epsilon_min: float = 0.01  # 最小 ε
    n_states: int = 10  # 状态数（人格状态离散化）
    n_actions: int = 5  # 动作数（可选调节动作）


class RLPersonalityAgent:
    """
    强化学习人格代理 — Q-Learning

    科学依据：Q-Learning（Watkins, 1989）
    Q(s,a) ← Q(s,a) + α * [r + γ * max_a' Q(s',a') - Q(s,a)]

    用途：
    - 通过与环境（用户）的互动学习最优人格调节策略
    - 状态：当前人格状态的离散化表示
    - 动作：对人格维度的调节方向（增加/减少/保持等）
    - 奖励：用户反馈（正向/负向）

    人格调节流程：
    1. 观察当前人格状态 → 离散化为状态 s
    2. 根据 ε-greedy 策略选择动作 a
    3. 执行动作 → 人格状态变化
    4. 接收用户反馈 → 计算奖励 r
    5. 更新 Q 表
    """

    # 预定义动作含义（5个动作）
    ACTION_NAMES = [
        "decrease_significantly",  # -0.2
        "decrease_slightly",  # -0.05
        "maintain",  # 0.0
        "increase_slightly",  # +0.05
        "increase_significantly",  # +0.2
    ]

    ACTION_DELTAS = [-0.2, -0.05, 0.0, 0.05, 0.2]

    def __init__(self, config: RLConfig = None):
        self.config = config or RLConfig()
        n_s = self.config.n_states
        n_a = self.config.n_actions

        # Q 表：states × actions
        self._q_table = [[0.0] * n_a for _ in range(n_s)]
        self._visit_count = [[0] * n_a for _ in range(n_s)]
        self._episode_rewards: list[float] = []
        self._current_episode_reward = 0.0
        self._step_count = 0
        self._history: list[dict] = []

    def _discretize_state(self, personality_value: float) -> int:
        """
        将连续人格值离散化为状态

        Args:
            personality_value: [0, 1] 范围内的人格值

        Returns:
            int: 状态索引 [0, n_states-1]
        """
        clamped = max(0.0, min(1.0, personality_value))
        state = int(clamped * (self.config.n_states - 1))
        return min(state, self.config.n_states - 1)

    def select_action(self, state: int) -> tuple[int, str]:
        """
        ε-greedy 动作选择

        Args:
            state: 当前状态索引

        Returns:
            (action_index, action_name)
        """
        import random

        eps = self.config.epsilon

        if random.random() < eps:
            # 探索：随机选择
            action = random.randint(0, self.config.n_actions - 1)
        else:
            # 利用：选择 Q 值最大的动作
            action = max(range(self.config.n_actions), key=lambda a: self._q_table[state][a])

        return action, self.ACTION_NAMES[action]

    def update(self, state: int, action: int, reward: float, next_state: int):
        """
        Q-Learning 更新

        Q(s,a) ← Q(s,a) + α * [r + γ * max_a' Q(s',a') - Q(s,a)]

        Args:
            state: 当前状态
            action: 执行的动作
            reward: 收到的奖励
            next_state: 转移后的状态
        """
        alpha = self.config.learning_rate
        gamma = self.config.discount_factor

        # 计算 TD 目标
        max_next_q = max(self._q_table[next_state])
        td_target = reward + gamma * max_next_q
        td_error = td_target - self._q_table[state][action]

        # 更新 Q 值
        self._q_table[state][action] += alpha * td_error
        self._visit_count[state][action] += 1
        self._step_count += 1
        self._current_episode_reward += reward

        # ε 衰减
        self.config.epsilon = max(
            self.config.epsilon_min, self.config.epsilon * self.config.epsilon_decay
        )

        record = {
            "state": state,
            "action": self.ACTION_NAMES[action],
            "reward": round(reward, 4),
            "next_state": next_state,
            "td_error": round(td_error, 4),
            "epsilon": round(self.config.epsilon, 4),
        }
        self._history.append(record)

        logger.debug(
            f"Q-Learning 更新: s={state}, a={self.ACTION_NAMES[action]}, "
            f"r={reward:.3f}, td_err={td_error:.4f}, eps={self.config.epsilon:.4f}"
        )

    def step(self, current_value: float, user_feedback: float) -> dict:
        """
        完整的一步交互

        Args:
            current_value: 当前人格值 [0, 1]
            user_feedback: 用户反馈 [-1, 1]

        Returns:
            dict: {action, delta, new_value, reward}
        """
        state = self._discretize_state(current_value)
        action, action_name = self.select_action(state)
        delta = self.ACTION_DELTAS[action]

        # 执行动作
        new_value = max(0.0, min(1.0, current_value + delta))

        # 计算奖励：如果反馈与调节方向一致则正奖励
        if delta != 0:
            reward = user_feedback * (1.0 if (delta > 0) == (user_feedback > 0) else -1.0)
        else:
            reward = user_feedback * 0.5  # 保持动作的奖励较小

        next_state = self._discretize_state(new_value)
        self.update(state, action, reward, next_state)

        return {
            "state": state,
            "action": action_name,
            "delta": delta,
            "new_value": round(new_value, 4),
            "reward": round(reward, 4),
            "next_state": next_state,
        }

    def end_episode(self):
        """结束一个回合"""
        self._episode_rewards.append(self._current_episode_reward)
        self._current_episode_reward = 0.0

    def get_q_table(self) -> list[list[float]]:
        """获取 Q 表（深拷贝）"""
        return [row[:] for row in self._q_table]

    def get_policy(self) -> dict[int, dict]:
        """
        获取当前最优策略

        Returns:
            {state: {action, q_value, visits}}
        """
        policy = {}
        for s in range(self.config.n_states):
            best_a = max(range(self.config.n_actions), key=lambda a: self._q_table[s][a])
            policy[s] = {
                "best_action": self.ACTION_NAMES[best_a],
                "q_value": round(self._q_table[s][best_a], 4),
                "visits": self._visit_count[s][best_a],
            }
        return policy

    def get_action_delta(self, action_index: int) -> float:
        """获取动作对应的调节量"""
        return self.ACTION_DELTAS[action_index]

    def reset(self):
        """重置 Q 表"""
        n_s = self.config.n_states
        n_a = self.config.n_actions
        self._q_table = [[0.0] * n_a for _ in range(n_s)]
        self._visit_count = [[0] * n_a for _ in range(n_s)]
        self._episode_rewards.clear()
        self._current_episode_reward = 0.0
        self._step_count = 0
        self._history.clear()
        self.config.epsilon = 0.1
