"""
EventBus — 模块间事件总线

职责：
- 模块间解耦通信
- 事件发布/订阅
- 异步事件处理

设计文档：DESIGN-V2.md §10.3

科学依据：
- 发布-订阅模式（Observer Pattern）
- 事件驱动架构（EDA）
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger("long_agent.session.event_bus")


class EventBus:
    """
    事件总线 — 模块间解耦通信

    使用方式：
        bus = EventBus()

        # 订阅
        bus.subscribe("memory.write", handler)

        # 发布
        await bus.publish("memory.write", {"content": "..."})
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._event_count: dict[str, int] = defaultdict(int)
        logger.info("EventBus 初始化完成")

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """订阅事件"""
        self._subscribers[event_type].append(handler)
        logger.debug(f"订阅事件: {event_type}, handler={handler.__name__}")

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """取消订阅"""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != handler
            ]

    async def publish(self, event_type: str, data: Any = None) -> int:
        """
        发布事件

        Args:
            event_type: 事件类型
            data: 事件数据

        Returns:
            int: 成功处理的事件处理器数量
        """
        self._event_count[event_type] += 1
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            return 0

        success = 0
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
                success += 1
            except Exception as e:
                logger.warning(f"事件处理器异常: {event_type}, error={e}")

        logger.debug(f"事件发布: {event_type}, handlers={len(handlers)}, success={success}")
        return success

    @property
    def event_types(self) -> list[str]:
        """所有已注册的事件类型"""
        return list(self._subscribers.keys())

    @property
    def stats(self) -> dict:
        """事件统计"""
        return dict(self._event_count)
