"""
单元测试 — ErrorClassifier

分类管道：HTTP 状态码 → 通用模式匹配
"""

import pytest

from src.errors.classifier import ErrorClassifier, ErrorType


@pytest.fixture
def c():
    return ErrorClassifier()


# ---- HTTP 状态码分类 ----


def test_401_auth(c):
    r = c.classify(Exception("401 Unauthorized"))
    assert r.error_type == ErrorType.AUTH
    assert r.retryable is False
    assert r.recoverable is False


def test_403_forbidden(c):
    r = c.classify(Exception("403 Forbidden"))
    assert r.error_type == ErrorType.AUTH
    assert r.retryable is False


def test_429_rate_limit(c):
    r = c.classify(Exception("429 Too Many Requests"))
    assert r.error_type == ErrorType.RATE_LIMIT
    assert r.retryable is True
    assert r.recoverable is True


def test_500_server(c):
    r = c.classify(Exception("500 Internal Server Error"))
    assert r.error_type == ErrorType.SERVER
    assert r.retryable is True


def test_502_bad_gateway(c):
    r = c.classify(Exception("502 Bad Gateway"))
    assert r.error_type == ErrorType.SERVER


def test_503_unavailable(c):
    r = c.classify(Exception("503 Service Unavailable"))
    assert r.error_type == ErrorType.SERVER


# ---- 通用模式分类 ----


def test_context_overflow(c):
    """context length exceeded → CONTEXT_OVERFLOW"""
    r = c.classify(Exception("context length exceeded"))
    assert r.error_type == ErrorType.CONTEXT_OVERFLOW
    assert r.retryable is False
    assert r.recoverable is True


def test_context_maximum(c):
    """maximum context → CONTEXT_OVERFLOW"""
    r = c.classify(Exception("maximum context length"))
    assert r.error_type == ErrorType.CONTEXT_OVERFLOW


def test_too_many_tokens(c):
    r = c.classify(Exception("too many tokens"))
    assert r.error_type == ErrorType.CONTEXT_OVERFLOW


def test_timeout(c):
    r = c.classify(Exception("Request timeout"))
    assert r.error_type == ErrorType.TIMEOUT
    assert r.retryable is True


def test_timeout_variant(c):
    r = c.classify(Exception("timed out"))
    assert r.error_type == ErrorType.TIMEOUT


def test_connection_refused(c):
    r = c.classify(Exception("Connection refused"))
    assert r.error_type == ErrorType.CONNECTION
    assert r.retryable is True


def test_connection_reset(c):
    r = c.classify(Exception("Connection reset by peer"))
    assert r.error_type == ErrorType.CONNECTION


def test_connection_error(c):
    r = c.classify(Exception("ConnectionError"))
    assert r.error_type == ErrorType.CONNECTION


def test_network_error(c):
    r = c.classify(Exception("network error"))
    assert r.error_type == ErrorType.CONNECTION


def test_rate_limit_pattern(c):
    """rate limit 模式匹配"""
    r = c.classify(Exception("rate limit exceeded"))
    assert r.error_type == ErrorType.RATE_LIMIT


def test_auth_pattern(c):
    """authentication 模式匹配"""
    r = c.classify(Exception("authentication failed"))
    assert r.error_type == ErrorType.AUTH


def test_billing_pattern(c):
    r = c.classify(Exception("insufficient quota"))
    assert r.error_type == ErrorType.BILLING
    assert r.retryable is False


def test_unknown_error(c):
    r = c.classify(Exception("something weird happened"))
    assert r.error_type == ErrorType.UNKNOWN
    assert r.retryable is False
    assert r.recoverable is False


# ---- 分类结果字段 ----


def test_error_message_preserved(c):
    r = c.classify(Exception("custom error message"))
    assert "custom error" in r.human_message or "未知错误" in r.human_message


def test_all_error_types_covered():
    """确保所有 ErrorType 枚举值都有对应的分类逻辑"""
    c = ErrorClassifier()
    test_cases = [
        ("401", ErrorType.AUTH),
        ("429", ErrorType.RATE_LIMIT),
        ("timeout", ErrorType.TIMEOUT),
        ("connection refused", ErrorType.CONNECTION),
        ("context length exceeded", ErrorType.CONTEXT_OVERFLOW),
        ("random xyz", ErrorType.UNKNOWN),
    ]
    for msg, expected_type in test_cases:
        r = c.classify(Exception(msg))
        assert r.error_type == expected_type, f"'{msg}' 应分类为 {expected_type}"


def test_recovery_action_present(c):
    """每个分类结果都有恢复动作"""
    r = c.classify(Exception("429"))
    assert len(r.recovery_action) > 0
