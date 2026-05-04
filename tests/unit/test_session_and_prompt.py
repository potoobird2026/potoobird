"""
会话管理 + PromptManager 单元测试
覆盖：SessionManager, EventBus, PromptManager
"""

import asyncio
import pytest

from src.session.session_manager import SessionManager, Session
from src.session.event_bus import EventBus
from src.llm.prompt_manager import PromptManager, PromptTemplate


# ======================== SessionManager ========================

class TestSessionManager:

    @pytest.fixture
    def mgr(self):
        return SessionManager(idle_timeout=60)

    @pytest.mark.asyncio
    async def test_create_session(self, mgr):
        session = await mgr.create_session(conversation_id="test-001")
        assert session.session_id is not None
        assert session.state == "active"
        assert session.conversation_id == "test-001"

    @pytest.mark.asyncio
    async def test_get_session_updates_activity(self, mgr):
        session = await mgr.create_session()
        sid = session.session_id
        original_time = session.last_active_at
        import time
        await asyncio.sleep(0.05)
        result = await mgr.get_session(sid)
        assert result is not None
        assert result.last_active_at >= original_time

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, mgr):
        result = await mgr.get_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_destroy_session(self, mgr):
        session = await mgr.create_session()
        sid = session.session_id
        assert await mgr.destroy_session(sid) is True
        assert await mgr.get_session(sid) is None

    @pytest.mark.asyncio
    async def test_destroy_nonexistent(self, mgr):
        assert await mgr.destroy_session("nonexistent") is False

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, mgr):
        mgr_short = SessionManager(idle_timeout=1)
        await mgr_short.create_session()
        assert mgr_short.active_count == 1
        import time
        await asyncio.sleep(1.5)
        cleaned = await mgr_short.cleanup_expired()
        assert cleaned >= 1

    @pytest.mark.asyncio
    async def test_active_count(self, mgr):
        assert mgr.active_count == 0
        await mgr.create_session()
        await mgr.create_session()
        assert mgr.active_count == 2

    @pytest.mark.asyncio
    async def test_session_with_context(self, mgr):
        session = await mgr.create_session(context={"key": "value"})
        assert session.context["key"] == "value"




class TestEventBus:

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, bus):
        received = []
        bus.subscribe("test.event", lambda data: received.append(data))
        count = await bus.publish("test.event", {"key": "value"})
        assert count == 1
        assert len(received) == 1
        assert received[0]["key"] == "value"

    @pytest.mark.asyncio
    async def test_publish_no_subscribers(self, bus):
        count = await bus.publish("no.subscriber", "data")
        assert count == 0

    @pytest.mark.asyncio
    async def test_async_handler(self, bus):
        received = []

        async def async_handler(data):
            received.append(data)

        bus.subscribe("async.event", async_handler)
        await bus.publish("async.event", "async-data")
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus):
        results = []
        bus.subscribe("multi.event", lambda d: results.append(f"a:{d}"))
        bus.subscribe("multi.event", lambda d: results.append(f"b:{d}"))
        await bus.publish("multi.event", "x")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_handler_exception_not_blocking(self, bus):
        results = []

        def bad_handler(data):
            raise RuntimeError("test error")

        def good_handler(data):
            results.append(data)

        bus.subscribe("err.event", bad_handler)
        bus.subscribe("err.event", good_handler)
        await bus.publish("err.event", "ok")
        assert results == ["ok"]

    def test_unsubscribe(self, bus):
        handler = lambda d: None
        bus.subscribe("unsub.event", handler)
        bus.unsubscribe("unsub.event", handler)
        assert handler not in bus._subscribers["unsub.event"]

    def test_event_types(self, bus):
        bus.subscribe("type.a", lambda d: None)
        bus.subscribe("type.b", lambda d: None)
        types = bus.event_types
        assert "type.a" in types
        assert "type.b" in types

    @pytest.mark.asyncio
    async def test_stats(self, bus):
        bus.subscribe("stat.event", lambda d: None)
        await bus.publish("stat.event")
        await bus.publish("stat.event")
        stats = bus.stats
        assert stats["stat.event"] == 2


# ======================== PromptManager ========================

class TestPromptManager:

    @pytest.fixture
    def mgr(self):
        return PromptManager()

    def test_default_templates_exist(self, mgr):
        templates = mgr.list_templates()
        assert "system_base" in templates
        assert "with_personality" in templates
        assert "intent_analysis" in templates
        assert "with_standards" in templates

    def test_get_template(self, mgr):
        t = mgr.get_template("system_base")
        assert t is not None
        assert t.name == "system_base"

    def test_get_nonexistent_template(self, mgr):
        assert mgr.get_template("nonexistent") is None

    def test_register_template(self, mgr):
        new_t = PromptTemplate(name="custom", template="Hello {name}", version="1.0")
        mgr.register_template(new_t)
        assert mgr.get_template("custom") is not None

    def test_build_system_prompt_basic(self, mgr):
        prompt = mgr.build_system_prompt(user_id="test")
        assert "test" in prompt

    def test_build_system_prompt_with_personality(self, mgr):
        prompt = mgr.build_system_prompt(
            personality={"H": 70, "E": 50, "X": 60, "A": 50, "C": 50, "O": 50}
        )
        # 模板格式: H(诚实-谦逊)=70
        assert "H(诚实-谦逊)=70" in prompt
        assert "X(外向性)=60" in prompt

    def test_build_system_prompt_with_memories(self, mgr):
        prompt = mgr.build_system_prompt(memories=["记忆1", "记忆2"])
        assert "记忆1" in prompt
        assert "记忆2" in prompt

    def test_build_system_prompt_with_standards(self, mgr):
        prompt = mgr.build_system_prompt(standards=["标准A", "标准B"])
        assert "标准A" in prompt
        assert "标准B" in prompt

    def test_build_system_prompt_full(self, mgr):
        prompt = mgr.build_system_prompt(
            personality={"H": 50, "E": 50, "X": 50, "A": 50, "C": 50, "O": 50},
            memories=["记忆1"],
            standards=["标准1"],
            user_id="full-test",
        )
        assert "H(诚实-谦逊)=50" in prompt
        assert "记忆1" in prompt
        assert "标准1" in prompt
        assert "full-test" in prompt

    def test_build_memories_limit(self, mgr):
        memories = [f"记忆{i}" for i in range(10)]
        prompt = mgr.build_system_prompt(memories=memories)
        # 最多5条
        assert "记忆0" in prompt
        assert "记忆9" not in prompt

    def test_build_standards_limit(self, mgr):
        standards = [f"标准{i}" for i in range(15)]
        prompt = mgr.build_system_prompt(standards=standards)
        assert "标准0" in prompt
        assert "标准14" not in prompt  # 最多10条
