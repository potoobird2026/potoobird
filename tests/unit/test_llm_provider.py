"""
单元测试 — LLM Provider（Mock OpenAI API）

不产生真实 API 费用，用 mock 替换 OpenAI 调用。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.errors.types import LLMResult
from src.llm.provider import LLMProvider, LLMRequest, OpenAIProvider

# ---- LLMProvider 抽象接口 ----


class DummyProvider(LLMProvider):
    """测试用虚拟 Provider"""

    def __init__(self, response_text="dummy response", should_fail=False):
        self._response = response_text
        self._should_fail = should_fail
        self.chat_called_with = None

    @property
    def provider_name(self):
        return "dummy"

    async def validate(self):
        return True

    async def chat(self, request: LLMRequest):
        self.chat_called_with = request
        if self._should_fail:
            return LLMResult.fail(error="模拟错误")
        return LLMResult.success(content=self._response)

    async def stream(self, request: LLMRequest):
        yield self._response


def test_abstract_interface():
    """LLMProvider 不能直接实例化（ABC）"""
    with pytest.raises(TypeError):
        LLMProvider()


def test_dummy_provider_success():
    """虚拟 Provider 正常返回"""

    async def run():
        p = DummyProvider("hello")
        req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
        result = await p.chat(req)
        assert result.is_ok
        assert result.content == "hello"

    import asyncio

    asyncio.run(run())


def test_dummy_provider_failure():
    """虚拟 Provider 失败返回"""

    async def run():
        p = DummyProvider(should_fail=True)
        req = LLMRequest(messages=[{"role": "user", "content": "hi"}])
        result = await p.chat(req)
        assert result.is_err
        assert result.error == "模拟错误"

    import asyncio

    asyncio.run(run())


def test_dummy_provider_passes_request():
    """虚拟 Provider 正确传递请求对象"""

    async def run():
        p = DummyProvider()
        req = LLMRequest(
            messages=[{"role": "user", "content": "test"}],
            model="gpt-4o",
            temperature=0.5,
            max_tokens=100,
        )
        await p.chat(req)
        assert p.chat_called_with.model == "gpt-4o"
        assert p.chat_called_with.temperature == 0.5
        assert p.chat_called_with.max_tokens == 100

    import asyncio

    asyncio.run(run())


def test_provider_name():
    """虚拟 Provider 有 provider_name"""
    p = DummyProvider()
    assert p.provider_name == "dummy"


# ---- LLMRequest ----


def test_llm_request_defaults():
    req = LLMRequest(messages=[])
    assert req.model == "gpt-4o"
    assert req.temperature == 0.7
    assert req.max_tokens == 2048
    assert req.timeout == 30


def test_llm_request_custom():
    req = LLMRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
        temperature=0.0,
    )
    assert req.model == "gpt-4o-mini"
    assert req.temperature == 0.0


# ---- OpenAIProvider Mock 测试 ----


def _make_mock_client(response=None, side_effect=None):
    """创建 mock OpenAI client"""
    mock_client = MagicMock()
    if side_effect:
        mock_client.chat.completions.create = AsyncMock(side_effect=side_effect)
    else:
        mock_client.chat.completions.create = AsyncMock(return_value=response)
    return mock_client


def _make_success_response(content="AI 回复", model="gpt-4o"):
    """创建成功响应 mock"""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    mock_response.model = model
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5
    mock_response.usage.total_tokens = 15
    mock_response.choices[0].finish_reason = "stop"
    return mock_response


@pytest.mark.asyncio
async def test_openai_chat_success():
    """OpenAI chat 正常返回"""
    mock_response = _make_success_response()
    mock_client = _make_mock_client(response=mock_response)

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_ok
    assert result.content == "AI 回复"
    assert result.model == "gpt-4o"


@pytest.mark.asyncio
async def test_openai_chat_api_error():
    """OpenAI API 返回错误"""
    mock_client = _make_mock_client(side_effect=Exception("401 Unauthorized"))

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_err
    assert "401" in result.error or "API Key" in result.error


@pytest.mark.asyncio
async def test_openai_chat_connection_error():
    """网络连接错误"""
    mock_client = _make_mock_client(
        side_effect=ConnectionError("Connection refused")
    )

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_err
    assert "连接" in result.error or "Connection" in result.error


@pytest.mark.asyncio
async def test_openai_chat_timeout():
    """请求超时"""
    import asyncio

    mock_client = _make_mock_client(
        side_effect=asyncio.TimeoutError("Request timed out")
    )

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_err


@pytest.mark.asyncio
async def test_openai_uses_correct_model():
    """验证使用了正确的模型"""
    mock_response = _make_success_response(content="ok")
    mock_client = _make_mock_client(response=mock_response)

    provider = OpenAIProvider(api_key="sk-test-key", model="gpt-4o")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "test"}], model="gpt-4o")
        await provider.chat(req)

    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args
    assert call_kwargs[1]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_openai_empty_response():
    """API 返回空响应"""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = ""
    mock_response.model = "gpt-4o"
    mock_response.choices[0].finish_reason = "length"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 1
    mock_response.usage.completion_tokens = 0
    mock_response.usage.total_tokens = 1
    mock_client = _make_mock_client(response=mock_response)

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_ok  # 空内容不是错误
    assert result.content == ""
    assert result.finish_reason == "length"


@pytest.mark.asyncio
async def test_openai_no_choices():
    """API 返回无 choices"""
    mock_response = MagicMock()
    mock_response.choices = []
    mock_client = _make_mock_client(response=mock_response)

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_err


@pytest.mark.asyncio
async def test_openai_context_overflow():
    """上下文过长错误"""
    mock_client = _make_mock_client(
        side_effect=Exception("maximum context length is 128000 tokens")
    )

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_err
    assert result.error_code.value == "context_overflow"


@pytest.mark.asyncio
async def test_openai_rate_limit():
    """429 限流错误"""
    mock_client = _make_mock_client(
        side_effect=Exception("429 rate limit exceeded")
    )

    provider = OpenAIProvider(api_key="sk-test-key")
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = LLMRequest(messages=[{"role": "user", "content": "你好"}])
        result = await provider.chat(req)

    assert result.is_err
    assert result.error_code.value == "rate_limit"


# ---- LLMResult 类型测试 ----


def test_llm_result_ok():
    r = LLMResult.success(content="hello")
    assert r.is_ok
    assert r.is_err is False
    assert r.content == "hello"
    assert r.error == ""


def test_llm_result_err():
    r = LLMResult.fail(error="出错了")
    assert r.is_err
    assert r.is_ok is False
    assert r.error == "出错了"
    assert r.content == ""


def test_llm_result_not_frozen():
    """LLMResult 不是 frozen，可以修改"""
    r = LLMResult(ok=True)
    r.content = "修改后"
    assert r.content == "修改后"
