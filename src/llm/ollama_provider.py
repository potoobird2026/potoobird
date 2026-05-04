"""Ollama 本地模型 Provider"""

import logging

from src.errors.types import ErrorCode, LLMResult

logger = logging.getLogger("long_agent.llm.ollama")

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class OllamaProvider:
    """Ollama 本地模型 Provider"""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3",
        timeout: int = 60,
    ):
        if not HAS_HTTPX:
            raise ImportError("httpx 包未安装。请运行：pip install httpx")
        self._base_url = base_url
        self._model = model
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def validate(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._base_url}/api/tags", timeout=5)
                return resp.status_code == 200
        except Exception:
            return False

    async def chat(self, request) -> LLMResult:
        try:
            messages = []
            for msg in request.messages:
                messages.append(
                    {
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", ""),
                    }
                )

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": getattr(request, "temperature", 0.7),
                        },
                    },
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "")

            return LLMResult.success(content=content, model=self._model)
        except Exception as e:
            return LLMResult.fail(error=str(e), code=ErrorCode.CONNECTION_ERROR)
