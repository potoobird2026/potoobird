"""Anthropic Claude Provider"""

import logging
from abc import ABC

from src.errors.types import ErrorCode, LLMResult

logger = logging.getLogger("long_agent.llm.anthropic")

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class AnthropicProvider:
    """Anthropic Claude Provider"""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022", timeout: int = 30):
        if not HAS_ANTHROPIC:
            raise ImportError("anthropic 包未安装。请运行：pip install anthropic")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def validate(self) -> bool:
        return self._api_key.startswith("sk-ant-")

    async def chat(self, request) -> LLMResult:
        try:
            response = await self._client.messages.create(
                model=self._model,
                messages=request.messages,
                max_tokens=getattr(request, 'max_tokens', 2048),
                temperature=getattr(request, 'temperature', 0.7),
            )
            content = response.content[0].text if response.content else ""
            return LLMResult.success(
                content=content,
                model=self._model,
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            )
        except Exception as e:
            return LLMResult.fail(error=str(e), code=ErrorCode.SERVER_ERROR)
