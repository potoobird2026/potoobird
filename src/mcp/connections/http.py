"""
HTTP MCP 连接 — 通过 HTTP POST 与 MCP 服务端通信

支持 Streamable HTTP 或 SSE 端点。
使用 httpx.AsyncClient 发起异步 HTTP 请求。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.mcp.connections.base import McpConnection

logger = logging.getLogger("long_agent.mcp.connections.http")


class HttpMcpConnection(McpConnection):
    """
    通过 HTTP POST 与 MCP 服务端通信。

    使用 httpx.AsyncClient 发起异步 HTTP 请求，
    支持自定义 headers（认证令牌等）。
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.client: httpx.AsyncClient | None = None
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.client is not None

    async def connect(self) -> None:
        """创建 HTTP 客户端会话"""
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(self.timeout),
        )
        self._connected = True
        logger.info(f"HTTP MCP 客户端已创建: {self.url}")

    async def send(self, message: dict[str, Any]) -> None:
        """
        发送 JSON-RPC 请求（HTTP 模式下不单独使用，
        请用 send_and_receive 原子操作）。
        """
        # HTTP 模式下 send 不直接使用，但为了接口一致性保留
        logger.debug("HTTP MCP: send() 不单独使用，请使用 send_and_receive()")

    async def receive(self) -> dict[str, Any]:
        """
        读取响应（HTTP 模式下不单独使用）。
        """
        raise NotImplementedError("HTTP MCP 不支持独立 receive()，请使用 send_and_receive()")

    async def send_and_receive(self, message: dict[str, Any]) -> dict[str, Any]:
        """POST JSON-RPC 请求，返回响应"""
        if not self.is_connected or self.client is None:
            raise ConnectionError("HTTP MCP 未连接")

        try:
            response = await self.client.post(
                self.url,
                json=message,
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as e:
            raise TimeoutError(f"HTTP MCP 请求超时: {e}") from e
        except httpx.HTTPStatusError as e:
            raise ConnectionError(
                f"HTTP MCP HTTP 错误 {e.response.status_code}: {e.response.text[:200]}"
            ) from e
        except httpx.RequestError as e:
            raise ConnectionError(f"HTTP MCP 请求失败: {e}") from e

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        self._connected = False
        if self.client:
            await self.client.aclose()
            self.client = None
        logger.info("HTTP MCP 客户端已关闭")
