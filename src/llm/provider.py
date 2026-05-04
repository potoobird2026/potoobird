"""
LLM 抽象接口

设计原则：
- 接口和实现分离（DESIGN.md 原则 7）
- V1 只实现 OpenAI，V2 添加其他 Provider
- V2 换模型不改核心代码
- 错误不静默吞掉（红线 3）：返回 LLMResult.ok=False + error 字段
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.errors.types import ErrorCode, LLMResult

logger = logging.getLogger("long_agent.llm")


@dataclass
class LLMRequest:
    """LLM 请求"""

    messages: list[dict]  # [{"role": "user", "content": "..."}]
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 30


class LLMProvider(ABC):
    """
    LLM 抽象接口

    V1 实现：OpenAIProvider
    V2 实现：AnthropicProvider / GoogleProvider / 自定义端点
    """

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResult:
        """非流式调用，返回 LLMResult（ok=False 表示出错）"""
        ...

    @abstractmethod
    async def validate(self) -> bool:
        """验证 API Key 格式（不做网络验证）"""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...


class OpenAIProvider(LLMProvider):
    """OpenAI Provider — V1 实现"""

    def __init__(
        self, api_key: str, model: str = "gpt-4o", timeout: int = 30, max_retries: int = 3
    ):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries

        # 延迟导入（减少启动时间）
        self._client = None

    @property
    def provider_name(self) -> str:
        return "openai"

    def _get_client(self):
        """延迟初始化 OpenAI 客户端"""
        if self._client is None:
            try:
                import openai

                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key,
                    timeout=self._timeout,
                    max_retries=self._max_retries,
                )
            except ImportError:
                raise ImportError("openai 包未安装。请运行：pip install openai")
        return self._client

    async def validate(self) -> bool:
        """验证 API Key 格式：sk- 开头"""
        return self._api_key.startswith("sk-")

    async def chat(self, request: LLMRequest) -> LLMResult:
        """
        调用 OpenAI Chat Completions API

        返回 LLMResult：
        - 成功：ok=True, content 有值
        - 失败：ok=False, error 有值, error_code 标识错误类型
        """
        # 先验证 Key 格式
        if not await self.validate():
            return LLMResult.fail(
                error="API Key 格式无效（应以 sk- 开头）",
                code=ErrorCode.AUTH_ERROR,
            )

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=request.model,
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            choice = response.choices[0]
            usage = response.usage
            content = choice.message.content or ""

            # 成功但内容为空（模型返回空）— 不是错误，但需要明确
            if not content:
                logger.warning(
                    f"OpenAI 返回空内容，model={response.model}，"
                    f"finish_reason={choice.finish_reason}"
                )

            return LLMResult.success(
                content=content,
                model=response.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                finish_reason=choice.finish_reason or "",
            )

        except ImportError as e:
            logger.error(f"OpenAI SDK 未安装: {e}")
            return LLMResult.fail(
                error=str(e),
                code=ErrorCode.SERVER_ERROR,
            )
        except Exception as e:
            error_str = str(e).lower()
            # 根据错误消息分类
            if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str:
                code = ErrorCode.AUTH_ERROR
                msg = "API Key 无效"
            elif "429" in error_str or "rate limit" in error_str:
                code = ErrorCode.RATE_LIMIT
                msg = "请求太频繁，稍后重试"
            elif "timeout" in error_str or "timed out" in error_str:
                code = ErrorCode.TIMEOUT
                msg = "请求超时"
            elif "context length" in error_str or "maximum context" in error_str:
                code = ErrorCode.CONTEXT_OVERFLOW
                msg = "上下文过长，需要压缩"
            elif "500" in error_str or "503" in error_str or "server error" in error_str:
                code = ErrorCode.SERVER_ERROR
                msg = "服务端错误"
            elif "connection" in error_str:
                code = ErrorCode.CONNECTION_ERROR
                msg = "网络连接错误"
            else:
                code = ErrorCode.UNKNOWN
                msg = f"未知错误: {e}"

            logger.error(f"OpenAI 调用失败 [{code.value}]: {e}")
            return LLMResult.fail(error=f"{msg}（详情: {e}）", code=code)
