"""
统一错误处理类型

原则（DESIGN.md 红线 3）：
- 错误不能静默吞掉
- 所有错误必须有明确类型、可读消息、恢复动作
- 三种错误统一用 OperationResult 包装
"""

from dataclasses import dataclass, field
from enum import Enum


class ErrorCode(Enum):
    """错误码"""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    CONNECTION_ERROR = "connection_error"
    SERVER_ERROR = "server_error"
    SECURITY_VIOLATION = "security_violation"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


@dataclass
class OperationResult:
    """
    统一操作结果

    所有模块的写操作都返回此类型，调用方必须检查 ok。
    """

    ok: bool = True
    error_code: ErrorCode = ErrorCode.SUCCESS
    error_message: str = ""
    data: dict = field(default_factory=dict)

    @staticmethod
    def success(**kwargs) -> "OperationResult":
        return OperationResult(ok=True, data=kwargs)

    @staticmethod
    def fail(code: ErrorCode, message: str, **kwargs) -> "OperationResult":
        return OperationResult(ok=False, error_code=code, error_message=message, data=kwargs)

    @property
    def is_ok(self) -> bool:
        return self.ok

    @property
    def is_err(self) -> bool:
        return not self.ok


@dataclass
class LLMResult:
    """
    LLM 调用结果（替代 LLMResponse）

    明确区分：
    - 成功：ok=True, content 有值
    - 失败：ok=False, error 有值, content 为空
    """

    ok: bool = True
    content: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    error: str = ""
    error_code: ErrorCode = ErrorCode.SUCCESS

    @staticmethod
    def success(
        content: str,
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        finish_reason: str = "",
    ) -> "LLMResult":
        return LLMResult(
            ok=True,
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
        )

    @staticmethod
    def fail(error: str, code: ErrorCode = ErrorCode.UNKNOWN) -> "LLMResult":
        return LLMResult(ok=False, error=error, error_code=code)

    @property
    def is_ok(self) -> bool:
        return self.ok

    @property
    def is_err(self) -> bool:
        return not self.ok
