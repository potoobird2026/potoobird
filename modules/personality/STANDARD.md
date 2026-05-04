# 人格算法 — 模块标准

> **版本**：v2.1 | **日期**：2026-05-03
> **设计文档**：01_记忆系统全局设计.md §人格系统

---

## 一、模块定位

人格算法模块是 Agent 的"性格调节器"，用控制论算法（PID + 卡尔曼滤波 + 模糊控制）动态调节 Agent 的人格状态，使其行为与目标人格一致。

**核心约束（主心骨）**：
> **三算法融合：PID 控制器调节偏差 + 卡尔曼滤波最优状态估计 + 模糊控制处理不确定性。所有参数不写死，由公式/LLM/用户互动三个维度获得。人格状态向量（HEXACO六维）持续追踪，动态调节。**

---

## 二、接口规范

> 详见 `CONTRACT.md`

---

## 三、模块规则

### PE-001：PIDController — PID 控制器

**科学依据**：PID 控制（Proportional-Integral-Derivative, 1922）

**用途**：根据当前人格状态与目标的偏差，计算调节量
- 比例项（P）：响应当前偏差
- 积分项（I）：消除稳态误差
- 微分项（D）：预测未来趋势

**参数**：
- kp/ki/kd：默认值仅初始化用，运行后由 Ziegler-Nichols 方法在线整定
- setpoint：人格目标状态（由 LLM 根据用户偏好动态评估）
- output_min/output_max：[0.0, 1.0]
- integral_limit：防积分饱和

**自动调参**：`auto_tune(oscillation_period)` — Ziegler-Nichols 公式

### PE-002：KalmanFilter1D — 卡尔曼滤波器

**科学依据**：卡尔曼滤波（Kalman, 1960）

**用途**：从带有噪声的观测数据中估计真实人格状态
- 预测步骤：根据模型预测下一状态
- 更新步骤：结合观测值修正预测

**自适应噪声**：`adapt_noise(residual_history)` — 根据残差方差动态调整 R

### PE-003：FuzzyController — 模糊控制器

**科学依据**：模糊集合理论（Zadeh, 1965）+ Mamdani 模糊推理（1974）

**用途**：处理人格调节中的不确定性和模糊性
- 模糊化：精确输入 → 模糊集（三角形隶属函数）
- 规则推理：7条默认规则（可由 LLM 动态调整）
- 去模糊化：重心法（COG）

**模糊集**：
- 输入：error（5个模糊集）+ delta（3个模糊集）
- 输出：5个调节量模糊集

### PE-004：人格状态向量（HEXACO）

| 维度 | 全称 | 说明 |
|------|------|------|
| H | Honesty-Humility | 诚实-谦逊 |
| E | Emotionality | 情绪性 |
| X | eXtraversion | 外向性 |
| A | Agreeableness | 宜人性 |
| C | Conscientiousness | 尽责性 |
| O | Openness | 开放性 |

每个维度值域 [0.0, 1.0]，三算法分别对不同维度独立调节。

### PE-005：参数不写死
- PID 参数：Ziegler-Nichols 在线整定
- 卡尔曼噪声：自适应调整
- 模糊规则：LLM 根据用户反馈动态调整
- setpoint：LLM 根据用户偏好动态评估

---

## 四、依赖

- **全局标准**：`GLOBAL_STANDARDS.md`
- **依赖模块**：`config`（读取人格参数）
- **被依赖模块**：`loop`（AgentLoop 调用人格算法调节行为）

---

## 五、变更记录

| 日期 | 变更内容 |
|------|----------|
| 2026-05-03 | 初版创建（代码已有，modules目录缺失） |
| 2026-05-03 | 补全：基于 personality/algorithms.py 实际代码 + 01_全局设计§人格系统，添加 PE-001~PE-005 规则，三算法融合，HEXACO六维，参数自适应 |
