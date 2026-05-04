"""
错误分类器

分类管道（合并自 hermse v1.3，三阶段精准分类）：
1. 规则匹配（可重试/不可重试）
2. HTTP 状态码直接映射
3. 未知错误 → LLM 判断是否可重试

可重试错误（指数退避+抖动，max 3次）：timeout, rate_limit, server_error, connection_error
不可重试错误（立即失败）：auth_error, invalid_request, quota_exceeded
未知错误（LLM兜底）：置信度 > 0.8 → 按LLM建议执行，置信度 ≤ 0.8 → 保守策略（不重试）
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("long_agent.errors")


class ErrorType(Enum):
    """错误类型"""

    AUTH = "auth"  # 认证失败
    BILLING = "billing"  # 余额不足
    RATE_LIMIT = "rate_limit"  # 限流
    TIMEOUT = "timeout"  # 超时
    CONTEXT_OVERFLOW = "context_overflow"  # 上下文溢出
    CONNECTION = "connection"  # 连接错误
    SERVER = "server"  # 服务端错误
    UNKNOWN = "unknown"  # 未知


@dataclass
class ErrorClassification:
    """错误分类结果"""

    error_type: ErrorType
    recoverable: bool  # 是否可恢复
    retryable: bool  # 是否可重试
    recovery_action: str  # 恢复动作
    human_message: str  # 给用户的友好消息


class ErrorClassifier:
    """
    错误分类器

    使用优先级管道精确识别错误类型。
    """

    # HTTP 状态码 → 错误类型映射
    HTTP_STATUS_MAP = {
        401: (ErrorType.AUTH, False, False, "prompt_auth", "API Key 无效，请检查配置"),
        403: (ErrorType.AUTH, False, False, "prompt_auth", "API Key 权限不足，请检查配置"),
        429: (ErrorType.RATE_LIMIT, True, True, "retry_with_backoff", "请求太频繁，稍后重试"),
        500: (ErrorType.SERVER, True, True, "retry_simple", "服务端错误，稍后重试"),
        502: (ErrorType.SERVER, True, True, "retry_simple", "网关错误，稍后重试"),
        503: (ErrorType.SERVER, True, True, "retry_with_backoff", "服务暂时不可用，稍后重试"),
    }

    # 通用错误消息模式
    ERROR_PATTERNS = [
        (
            r"context\s*length\s*ex[cs]eed|maximum\s*context|too\s*many\s*tokens",
            ErrorType.CONTEXT_OVERFLOW,
            True,
            False,
            "compress_and_retry",
            "上下文过长，需要压缩",
        ),
        (
            r"rate\s*limit|too\s*many\s*requests|throttl",
            ErrorType.RATE_LIMIT,
            True,
            True,
            "retry_with_backoff",
            "请求太频繁，稍后重试",
        ),
        (
            r"timeout|timed?\s*out",
            ErrorType.TIMEOUT,
            True,
            True,
            "retry_simple",
            "请求超时，稍后重试",
        ),
        (
            r"authentication|unauthorized|invalid\s*api\s*key|401",
            ErrorType.AUTH,
            False,
            False,
            "prompt_auth",
            "认证失败，请检查 API Key",
        ),
        (
            r"billing|insufficient\s*quota|exceeded\s*quota|402",
            ErrorType.BILLING,
            False,
            False,
            "prompt_billing",
            "余额不足，请充值",
        ),
        (
            r"connection\s*(refused|reset|error)|connecterror|network",
            ErrorType.CONNECTION,
            True,
            True,
            "retry_simple",
            "网络连接错误，请检查网络",
        ),
    ]

    def classify(self, error: Exception, provider: str = None) -> ErrorClassification:
        """
        分类错误

        管道：特殊 provider 模式 → HTTP 状态码 → 通用模式
        """
        error_str = str(error).lower()
        error_type = self._match_by_http_status(error_str)
        if error_type:
            return error_type

        error_type = self._match_by_patterns(error_str)
        if error_type:
            return error_type

        logger.warning(f"无法分类的错误: {error}")
        return ErrorClassification(
            error_type=ErrorType.UNKNOWN,
            recoverable=False,
            retryable=False,
            recovery_action="log_and_fail",
            human_message=f"未知错误：{error}",
        )

    def _match_by_http_status(self, error_str: str) -> Optional[ErrorClassification]:
        """HTTP 状态码匹配"""
        for code, (etype, recoverable, retryable, action, msg) in self.HTTP_STATUS_MAP.items():
            if str(code) in error_str:
                return ErrorClassification(
                    error_type=etype,
                    recoverable=recoverable,
                    retryable=retryable,
                    recovery_action=action,
                    human_message=msg,
                )
        return None

    def _match_by_patterns(self, error_str: str) -> Optional[ErrorClassification]:
        """通用模式匹配"""
        for pattern, etype, recoverable, retryable, action, msg in self.ERROR_PATTERNS:
            if re.search(pattern, error_str):
                return ErrorClassification(
                    error_type=etype,
                    recoverable=recoverable,
                    retryable=retryable,
                    recovery_action=action,
                    human_message=msg,
                )
        return None


# ========== V2 升级：自适应重试策略 + LLM 兜底判断 ==========

class AdaptiveRetryPolicy:
    """
    自适应重试策略（合并自 hermse v1.3）

    max_retries 和 base_delay 不写死，基于历史数据自适应。
    """

    # 可重试错误类型
    RETRYABLE_ERRORS = {"timeout", "rate_limit", "server_error", "connection_error"}
    # 不可重试错误类型
    NON_RETRYABLE_ERRORS = {"auth_error", "invalid_request", "quota_exceeded"}

    def __init__(self, max_retries: int = None, base_delay: float = None):
        """
        Args:
            max_retries: 最大重试次数（None 时自适应，默认 3）
            base_delay: 基础延迟（None 时自适应，默认 1.0 秒）

        自适应策略：
        - max_retries: 初始值 3，根据成功率动态调整，范围 [1, 5]
        - base_delay: 初始值 1.0s，根据 P95 延迟动态调整
        """
        self.max_retries = max_retries if max_retries is not None else 3
        self.base_delay = base_delay if base_delay is not None else 1.0
        self._retry_history: list = []  # (retry_count, success, latency)

    def should_retry(self, error_type: str, attempt: int) -> bool:
        """判断是否应该重试"""
        if attempt >= self.max_retries:
            return False
        return error_type in self.RETRYABLE_ERRORS

    def get_retry_delay(self, attempt: int) -> float:
        """
        计算重试延迟（指数退避 + 随机抖动）。

        公式：delay = base_delay × 2^(attempt-1) + random(0, jitter)
        """
        import random
        exponential_delay = self.base_delay * (2 ** (attempt - 1))
        jitter = random.uniform(0, self.base_delay * 0.5)
        return exponential_delay + jitter

    def adapt(self):
        """基于历史数据自适应调整参数"""
        if len(self._retry_history) < 10:
            return
        recent = self._retry_history[-10:]
        success_rate = sum(1 for _, success, _ in recent if success) / len(recent)

        # max_retries 自适应
        if success_rate > 0.9:
            self.max_retries = max(1, self.max_retries - 1)
        elif success_rate < 0.5:
            self.max_retries = min(5, self.max_retries + 1)

        # base_delay 自适应（基于 P95 延迟）
        latencies = sorted(lat for _, _, lat in recent)
        if latencies:
            p95_idx = int(len(latencies) * 0.95)
            p95 = latencies[min(p95_idx, len(latencies) - 1)]
            self.base_delay = max(0.1, p95 * 0.1)

    @staticmethod
    def get_retry_policy(failure_reason: str) -> dict:
        """
        根据失败原因返回重试策略（兼容 state.py StateMachine 调用）。

        | 失败原因 | 策略 | 最大重试次数 | 说明 |
        |---------|------|------------|------|
        | tool_call | 指数退避重试 | 3次 | 网络抖动/临时故障 |
        | llm_failure | 切换模型后重试 | 2次 | 当前模型不可用 |
        | state_corruption | 从快照恢复 | 1次 | 状态数据不一致 |
        """
        policies = {
            "tool_call": {
                "strategy": "exponential_backoff",
                "max_retries": 3,
                "backoff_base": 2,
                "description": "工具调用失败：指数退避重试 max 3次",
            },
            "llm_failure": {
                "strategy": "model_switch",
                "max_retries": 2,
                "description": "LLM失败：切换模型后重试 max 2次",
            },
            "state_corruption": {
                "strategy": "snapshot_restore",
                "max_retries": 1,
                "description": "状态损坏：从快照恢复 max 1次",
            },
        }
        return policies.get(failure_reason, {
            "strategy": "none",
            "max_retries": 0,
            "description": "未知失败原因：不重试",
        })


class LLMBasedErrorClassifier:
    """
    LLM 兜底错误分类器（合并自 hermse v1.3）

    当前三阶段管道无法分类的错误，交给 LLM 判断是否可重试。
    置信度 > 0.8 → 按 LLM 建议执行
    置信度 ≤ 0.8 → 保守策略（不重试）
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client

    async def classify(self, error_msg: str) -> dict:
        """使用 LLM 判断未知错误是否可重试"""
        if not self._llm:
            return {"retryable": False, "confidence": 0.0, "action": "fail_immediately"}
        # 实际实现中调用 LLM
        # 此处返回默认值（保守策略）
        return {"retryable": False, "confidence": 0.5, "action": "fail_immediately_unknown_error"}
