"""
EventBus — 单元测试

覆盖：订阅/取消订阅、发布（同步+异步handler）、统计、事件类型
"""

import pytest

from src.session.event_bus import EventBus


@pytest.fixture
def bus():
    return EventBus()


class TestEventBusSubscribe:
    def test_subscribe(self, bus):
        def handler(data): return None
        bus.subscribe("test.event", handler)
        assert "test.event" in bus.event_types

    def test_subscribe_multiple_handlers(self, bus):
        bus.subscribe("test.event", lambda d: None)
        bus.subscribe("test.event", lambda d: None)
        assert len(bus._subscribers["test.event"]) == 2

    def test_subscribe_different_events(self, bus):
        bus.subscribe("event.a", lambda d: None)
        bus.subscribe("event.b", lambda d: None)
        assert set(bus.event_types) == {"event.a", "event.b"}


class TestEventBusUnsubscribe:
    def test_unsubscribe(self, bus):
        def h1(d): return None
        def h2(d): return None
        bus.subscribe("test.event", h1)
        bus.subscribe("test.event", h2)
        bus.unsubscribe("test.event", h1)
        assert h1 not in bus._subscribers["test.event"]
        assert h2 in bus._subscribers["test.event"]

    def test_unsubscribe_nonexistent_type(self, bus):
        # 不应抛异常
        bus.subscribe("exists", lambda d: None)
        bus.unsubscribe("nonexistent", lambda d: None)


class TestEventBusPublish:
    @pytest.mark.asyncio
    async def test_publish_sync_handler(self, bus):
        results = []
        bus.subscribe("test.event", lambda data: results.append(data))
        count = await bus.publish("test.event", {"key": "value"})
        assert count == 1
        assert results == [{"key": "value"}]

    @pytest.mark.asyncio
    async def test_publish_async_handler(self, bus):
        results = []
        async def handler(data):
            results.append(data)
        bus.subscribe("test.event", handler)
        count = await bus.publish("test.event", "hello")
        assert count == 1
        assert results == ["hello"]

    @pytest.mark.asyncio
    async def test_publish_multiple_handlers(self, bus):
        count = 0
        def h1(d):
            nonlocal count
            count += 1
        def h2(d):
            nonlocal count
            count += 1
        bus.subscribe("test.event", h1)
        bus.subscribe("test.event", h2)
        result = await bus.publish("test.event")
        assert result == 2

    @pytest.mark.asyncio
    async def test_publish_no_handlers(self, bus):
        count = await bus.publish("no.handlers", "data")
        assert count == 0

    @pytest.mark.asyncio
    async def test_publish_handler_exception_doesnt_break_others(self, bus):
        results = []
        def bad_handler(d):
            raise RuntimeError("boom")
        def good_handler(d):
            results.append(d)
        bus.subscribe("test.event", bad_handler)
        bus.subscribe("test.event", good_handler)
        count = await bus.publish("test.event", "data")
        # bad_handler 抛异常，good_handler 仍应执行
        assert count == 1
        assert results == ["data"]


class TestEventBusStats:
    @pytest.mark.asyncio
    async def test_event_count(self, bus):
        bus.subscribe("test.event", lambda d: None)
        await bus.publish("test.event")
        await bus.publish("test.event")
        await bus.publish("other.event")
        stats = bus.stats
        assert stats["test.event"] == 2
        assert stats["other.event"] == 1

    def test_event_types_empty(self, bus):
        assert bus.event_types == []
