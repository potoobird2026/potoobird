"""
Skill 安全沙箱

提供 Skill handler 的隔离执行环境：
- SandboxResult：执行结果封装
- run_in_executor：带超时的线程池执行
"""

import asyncio
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("long_agent.skill")


@dataclass
class SandboxResult:
    """沙箱执行结果"""

    success: bool = False
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0
    timed_out: bool = False


def run_in_executor(
    handler: Callable,
    params: dict,
    timeout: int = 30,
    executor: Optional[ThreadPoolExecutor] = None,
) -> SandboxResult:
    """
    在线程池中执行 handler，带超时保护

    Args:
        handler: 要执行的函数（同步或异步）
        params: 参数字典
        timeout: 超时秒数（默认 30）
        executor: 可选的线程池（不传则用 asyncio 默认）

    Returns:
        SandboxResult
    """
    import time

    start = time.monotonic()
    result = SandboxResult()

    try:
        if asyncio.iscoroutinefunction(handler):
            # 异步 handler：在事件循环中运行
            loop = asyncio.get_event_loop()
            coro = handler(**params)
            task = asyncio.ensure_future(coro)
            # 使用 wait_for 实现超时
            try:
                result.result = asyncio.get_event_loop().run_until_complete(
                    asyncio.wait_for(coro, timeout=timeout)
                )
                result.success = True
            except asyncio.TimeoutError:
                task.cancel()
                result.timed_out = True
                result.error = f"执行超时（{timeout}s）"
        else:
            # 同步 handler：在线程池中运行
            if executor is None:
                executor = ThreadPoolExecutor(max_workers=1)
                _own_executor = True
            else:
                _own_executor = False

            future = executor.submit(handler, **params)
            try:
                result.result = future.result(timeout=timeout)
                result.success = True
            except TimeoutError:
                future.cancel()
                result.timed_out = True
                result.error = f"执行超时（{timeout}s）"
            except Exception as e:
                result.error = f"{type(e).__name__}: {e}"
                logger.error("沙箱执行异常: %s\n%s", e, traceback.format_exc())
            finally:
                if _own_executor:
                    executor.shutdown(wait=False)

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        logger.error("沙箱执行异常: %s\n%s", e, traceback.format_exc())

    result.duration_ms = (time.monotonic() - start) * 1000
    return result
