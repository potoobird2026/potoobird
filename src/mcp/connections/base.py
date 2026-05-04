"""
MCP 连接抽象基类

所有传输方式必须实现：
- connect()   建立连接
- send()      发送 JSON-RPC 请求
- receive()   接收 JSON-RPC 响应（仅 stdio 需要独立接收）
- close()     关闭连接
"""

from __future__ import annotations

import abc
from typing import Any


class McpConnection(abc.ABC):
    """
    MCP 传输连接抽象基类

    两种传输方式：
    - StdioMcpConnection: 子进程 stdin/stdout 管道
    - HttpMcpConnection:  HTTP POST
    """

    @abc.abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        ...

    @abc.abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        """发送 JSON-RPC 请求"""
        ...

    @abc.abstractmethod
    async def receive(self) -> dict[str, Any]:
        """读取一条 JSON-RPC 响应"""
        ...

    @abc.abstractmethod
    async def send_and_receive(self, message: dict[str, Any]) -> dict[str, Any]:
        """发送请求并等待响应（原子操作）"""
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        """关闭连接"""
        ...

    @abc.abstractmethod
    @property
    def is_connected(self) -> bool:
        """连接是否存活"""
        ...
