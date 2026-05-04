"""SessionManager 单元测试"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestSession:
    def test_session_defaults(self):
        from src.session.session_manager import Session, SessionStatus
        s = Session()
        assert s.status == SessionStatus.ACTIVE
        assert s.messages == []
        assert s.context_summary == ""
        assert s.task_states == {}

    def test_session_id_property(self):
        from src.session.session_manager import Session
        s = Session()
        assert s.session_id == s.id

    def test_session_state_property(self):
        from src.session.session_manager import Session
        s = Session()
        assert s.state == "active"

    def test_session_conversation_id_property(self):
        from src.session.session_manager import Session
        s = Session()
        assert s.conversation_id == s.id

    def test_session_context_property(self):
        from src.session.session_manager import Session
        s = Session()
        assert s.context == {}

    def test_session_message_count(self):
        from src.session.session_manager import Session
        s = Session()
        s.messages = [{"role": "user"}, {"role": "assistant"}]
        assert s.message_count == 2

    def test_session_with_state_param(self):
        from src.session.session_manager import Session, SessionStatus
        s = Session(state="paused")
        assert s.status == SessionStatus.PAUSED

    def test_session_with_message_count(self):
        from src.session.session_manager import Session
        s = Session(message_count=5)
        assert len(s.messages) == 5


class TestSessionManager:
    def test_init(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        assert mgr.memory is None
        assert mgr.compressor is None
        assert mgr.event_bus is None

    def test_init_with_params(self):
        from src.session.session_manager import SessionManager
        mock_mm = MagicMock()
        mock_comp = MagicMock()
        mock_bus = MagicMock()
        mgr = SessionManager(memory_manager=mock_mm, compressor=mock_comp, event_bus=mock_bus)
        assert mgr.memory is mock_mm
        assert mgr.compressor is mock_comp
        assert mgr.event_bus is mock_bus

    def test_active_count_empty(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_on_message_returns_response(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager(memory_manager=AsyncMock(), compressor=AsyncMock(), event_bus=AsyncMock())  # noqa: E501
        response = await mgr.on_message("default", "user1", "你好")
        assert isinstance(response, str)

    @pytest.mark.asyncio
    async def test_on_message_appends_messages(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager(memory_manager=AsyncMock(), compressor=AsyncMock(), event_bus=AsyncMock())  # noqa: E501
        await mgr.on_message("default", "user1", "测试消息")
        sessions = [s for s in mgr._sessions.values() if s.universal_id]
        assert len(sessions) >= 1

    @pytest.mark.asyncio
    async def test_on_message_accumulates(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager(memory_manager=AsyncMock(), compressor=AsyncMock(), event_bus=AsyncMock())  # noqa: E501
        await mgr.on_message("default", "user1", "第一条")
        await mgr.on_message("default", "user1", "第二条")
        sessions = list(mgr._sessions.values())
        assert len(sessions) == 1
        assert len(sessions[0].messages) >= 2

    @pytest.mark.asyncio
    async def test_get_session(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        s = await mgr.create_session(user_id="user1", channel="default")
        result = await mgr.get_session(s.id)
        assert result is not None
        assert result.id == s.id

    @pytest.mark.asyncio
    async def test_get_session_nonexistent(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        result = await mgr.get_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_create_session(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        s = await mgr.create_session(user_id="user1", channel="default")
        assert s is not None
        assert s.universal_id == "user1"
        assert s.channel == "default"

    @pytest.mark.asyncio
    async def test_create_session_with_context(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        s = await mgr.create_session(user_id="user1", channel="default", context={"key": "val"})
        assert s.task_states == {"key": "val"}

    @pytest.mark.asyncio
    async def test_destroy_session(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        s = await mgr.create_session(user_id="user1")
        result = await mgr.destroy_session(s.id)
        assert result is True
        assert s.id not in mgr._sessions

    @pytest.mark.asyncio
    async def test_destroy_nonexistent(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        result = await mgr.destroy_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_archive_session(self):
        from src.session.session_manager import SessionManager, SessionStatus
        mgr = SessionManager()
        s = await mgr.create_session(user_id="user1")
        result = await mgr.archive_session(s.id)
        assert result is True
        assert s.status == SessionStatus.ARCHIVED

    @pytest.mark.asyncio
    async def test_archive_nonexistent(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        result = await mgr.archive_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_save_session(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager(memory_manager=AsyncMock())
        s = await mgr.create_session(user_id="user1")
        result = await mgr.save_session(s.id)
        assert result is True

    @pytest.mark.asyncio
    async def test_save_nonexistent(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        result = await mgr.save_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_sessions_by_universal_id(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        await mgr.create_session(user_id="user1", channel="wechat")
        await mgr.create_session(user_id="user1", channel="telegram")
        sessions = mgr.get_sessions_by_universal_id("user1")
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        from src.session.session_manager import SessionManager
        mgr = SessionManager()
        # Cleanup with very short timeout
        count = await mgr.cleanup_expired(max_idle_seconds=0)
        assert count >= 0
