"""
单元测试 — OperationResult / LLMResult / ErrorCode
"""

from src.errors.types import ErrorCode, LLMResult, OperationResult

# ---- OperationResult ----


def test_ok_result():
    r = OperationResult.success(key="value")
    assert r.is_ok
    assert r.is_err is False
    assert r.data == {"key": "value"}
    assert r.error_code == ErrorCode.SUCCESS
    assert r.error_message == ""


def test_ok_result_no_data():
    r = OperationResult.success()
    assert r.is_ok
    assert r.data == {}


def test_fail_result():
    r = OperationResult.fail(code=ErrorCode.NOT_FOUND, message="不存在")
    assert r.is_err
    assert r.is_ok is False
    assert r.error_code == ErrorCode.NOT_FOUND
    assert r.error_message == "不存在"


def test_fail_result_with_data():
    r = OperationResult.fail(code=ErrorCode.VALIDATION_ERROR, message="无效", field="name")
    assert r.is_err
    assert r.data == {"field": "name"}


# ---- ErrorCode ----


def test_all_error_codes():
    codes = {e.name for e in ErrorCode}
    expected = {
        "SUCCESS",
        "NOT_FOUND",
        "VALIDATION_ERROR",
        "AUTH_ERROR",
        "RATE_LIMIT",
        "TIMEOUT",
        "CONTEXT_OVERFLOW",
        "CONNECTION_ERROR",
        "SERVER_ERROR",
        "SECURITY_VIOLATION",
        "CONFLICT",
        "UNKNOWN",
    }
    assert codes == expected


# ---- LLMResult ----


def test_llm_result_ok():
    r = LLMResult.success(content="AI回复", model="gpt-4o")
    assert r.is_ok
    assert r.content == "AI回复"
    assert r.model == "gpt-4o"
    assert r.error == ""


def test_llm_result_err():
    r = LLMResult.fail(error="API 错误")
    assert r.is_err
    assert r.error == "API 错误"
    assert r.content == ""


def test_llm_result_err_with_code():
    r = LLMResult.fail(error="401", code=ErrorCode.AUTH_ERROR)
    assert r.error_code == ErrorCode.AUTH_ERROR


def test_llm_result_token_counts():
    r = LLMResult.success(content="test", prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert r.prompt_tokens == 10
    assert r.completion_tokens == 5
    assert r.total_tokens == 15


def test_llm_result_not_frozen():
    """LLMResult 不是 frozen，可以修改"""
    r = LLMResult(ok=True)
    r.content = "修改后"
    assert r.content == "修改后"
