"""
Stdio MCP 连接 — 通过子进程 stdin/stdout 进行 JSON-RPC 通信

协议格式：每行一个 JSON 消息（newline-delimited JSON）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from typing import Any

from src.mcp.connections.base import McpConnection

logger = logging.getLogger("long_agent.mcp.connections.stdio")


class StdioMcpConnection(McpConnection):
    """
    通过子进程 stdin/stdout 进行 JSON-RPC 通信。

    使用 subprocess.Popen 启动服务端进程，
    stdin 发送 JSON-RPC 请求，stdout 读取 JSON-RPC 响应。
    每行一个 JSON 消息（newline-delimited JSON）。
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ):
        self.command = command
        self.args = args or []
        self.env = env
        self.process: subprocess.Popen | None = None
        self._reader_task: asyncio.Task | None = None
        self._response_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id: int = 1
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.process is not None and self.process.poll() is None

    async def connect(self) -> None:
        """启动子进程，建立 stdin/stdout 管道"""
        env = self.env if self.env is not None else {**os.environ}

        # 使用 asyncio 子进程以便非阻塞读写
        self.process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # 启动后台读取任务
        self._reader_task = asyncio.create_task(self._read_loop())
        self._connected = True
        logger.info(f"Stdio MCP 子进程已启动: {self.command} {' '.join(self.args)}")

    async def _read_loop(self) -> None:
        """后台循环读取 stdout，将响应放入队列"""
        try:
            assert self.process is not None
            assert self.process.stdout is not None

            while True:
                line_bytes = await self.process.stdout.readline()
                if not line_bytes:
                    # EOF — 进程退出
                    logger.warning("Stdio MCP stdout EOF（子进程可能已退出）")
                    break

                line = line_bytes.decode("utf-8").strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug(f"Stdio MCP 跳过非 JSON 行: {line[:80]}")
                    continue

                # 如果是请求的响应（有 id），放入 pending
                msg_id = message.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        fut.set_result(message)
                else:
                    # 通知/服务器推送
                    await self._response_queue.put(message)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Stdio MCP 读取循环异常: {e}")
            # 唤醒所有 pending 的 future
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError(f"Stdio MCP 读取异常: {e}"))
            self._pending.clear()
        finally:
            self._connected = False

    def _next_id(self) -> int:
        """获取下一个请求 ID"""
        rid = self._next_id
        self._next_id += 1
        return rid

    async def send(self, message: dict[str, Any]) -> None:
        """发送 JSON-RPC 消息（不等待响应）"""
        if not self.is_connected:
            raise ConnectionError("Stdio MCP 未连接")

        assert self.process is not None
        assert self.process.stdin is not None

        line = json.dumps(message, ensure_ascii=False) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

    async def receive(self) -> dict[str, Any]:
        """读取一条 JSON-RPC 响应（阻塞等待）"""
        return await self._response_queue.get()

    async def send_and_receive(self, message: dict[str, Any]) -> dict[str, Any]:
        """
        发送请求并等待对应响应。

        如果 message 没有 id，自动分配一个。
        使用 Future 机制确保精确匹配请求-响应。
        """
        if not self.is_connected:
            raise ConnectionError("Stdio MCP 未连接")

        msg_id = message.get("id")
        if msg_id is None:
            msg_id = self._next_id()
            message["id"] = msg_id

        # 创建 Future 等待响应
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut

        try:
            await self.send(message)
            # 等待响应（带超时保护由调用方控制）
            response = await asyncio.wait_for(fut, timeout=60.0)
            return response
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise
        except Exception:
            self._pending.pop(msg_id, None)
            raise

    async def close(self) -> None:
        """终止子进程"""
        self._connected = False

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                # 等待优雅退出
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                    timeout=5.0,
                )
            except (asyncio.TimeoutError, Exception):
                try:
                    self.process.kill()
                    await asyncio.get_event_loop().run_in_executor(None, self.process.wait)
                except Exception:
                    pass

        logger.info("Stdio MCP 子进程已关闭")
