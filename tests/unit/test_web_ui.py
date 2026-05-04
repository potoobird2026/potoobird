"""
单元测试 — Web UI 入口 (src/entry/web_ui.py)

覆盖：
- FastAPI 路由注册
- get_agent() 初始化
- / (index) 路由
- /api/chat 路由
- /api/memory GET/POST/DELETE 路由
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_settings(tmp_path):
    s = MagicMock()
    s.log_level = "INFO"
    s.log_file = str(tmp_path / "agent.log")
    s.database_path = str(tmp_path / "memory.db")
    s.data_dir = str(tmp_path)
    s.openai_api_key = ""
    s.openai_model = "gpt-4o"
    return s


class TestGetAgent:
    def test_returns_dict_with_expected_keys(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            agent = web_ui.get_agent()
            assert "loop" in agent
            assert "memory" in agent
            assert "settings" in agent

    def test_singleton_pattern(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            agent1 = web_ui.get_agent()
            agent2 = web_ui.get_agent()
            assert agent1 is agent2


class TestRoutes:
    def test_app_exists(self):
        from src.entry import web_ui
        assert web_ui.app is not None

    def test_static_mount(self):
        from src.entry import web_ui
        route_paths = [r.path for r in web_ui.app.routes]
        assert "/static" in route_paths


class TestIndexRoute:
    @pytest.mark.asyncio
    async def test_index_returns_html(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        mock_settings.openai_api_key = ""
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None

            mock_memory = MagicMock()
            mock_memory.storage = MagicMock()
            mock_memory.storage.count = AsyncMock(return_value=42)
            mock_memory.personality = {"H": 50}

            with patch.object(web_ui, "get_agent", return_value={
                "loop": MagicMock(),
                "memory": mock_memory,
                "settings": mock_settings,
            }), patch.object(web_ui.templates, "TemplateResponse", return_value=MagicMock()):
                mock_request = MagicMock()
                result = await web_ui.index(mock_request)
                assert result is not None


class TestChatRoute:
    @pytest.mark.asyncio
    async def test_chat_success(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None

            mock_loop = MagicMock()
            mock_loop.run = AsyncMock(return_value="Hello!")

            mock_request = MagicMock()
            mock_request.json = AsyncMock(return_value={"message": "hi"})

            with patch.object(web_ui, "get_agent", return_value={
                "loop": mock_loop,
                "memory": MagicMock(),
                "settings": mock_settings,
            }):
                result = await web_ui.chat(mock_request)
                assert "response" in result
                assert result["response"] == "Hello!"

    @pytest.mark.asyncio
    async def test_chat_error(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None

            mock_loop = MagicMock()
            mock_loop.run = AsyncMock(side_effect=Exception("test error"))

            mock_request = MagicMock()
            mock_request.json = AsyncMock(return_value={"message": "hi"})

            with patch.object(web_ui, "get_agent", return_value={
                "loop": mock_loop,
                "memory": MagicMock(),
                "settings": mock_settings,
            }):
                result = await web_ui.chat(mock_request)
                assert "error" in result

    @pytest.mark.asyncio
    async def test_chat_empty_message(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None

            mock_loop = MagicMock()
            mock_loop.run = AsyncMock(return_value="")

            mock_request = MagicMock()
            mock_request.json = AsyncMock(return_value={})

            with patch.object(web_ui, "get_agent", return_value={
                "loop": mock_loop,
                "memory": MagicMock(),
                "settings": mock_settings,
            }):
                result = await web_ui.chat(mock_request)
                assert "response" in result


class TestMemoryRoutes:
    @pytest.mark.asyncio
    async def test_get_memories(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None

            mock_memory_obj = MagicMock()
            mock_memory_obj.id = "m1"
            mock_memory_obj.content = "test memory"
            mock_memory_obj.layer = "core"

            mock_memory = MagicMock()
            mock_memory.search = AsyncMock(return_value=[mock_memory_obj])

            with patch.object(web_ui, "get_agent", return_value={
                "loop": MagicMock(),
                "memory": mock_memory,
                "settings": mock_settings,
            }):
                result = await web_ui.get_memories()
                assert "memories" in result
                assert len(result["memories"]) == 1

    @pytest.mark.asyncio
    async def test_add_memory(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None

            mock_result = MagicMock()
            mock_result.id = "new_id"
            mock_result.created = "2025-01-01"

            mock_memory = MagicMock()
            mock_memory.remember = AsyncMock(return_value=mock_result)

            mock_request = MagicMock()
            mock_request.json = AsyncMock(return_value={"content": "new memory", "layer": "core"})

            with patch.object(web_ui, "get_agent", return_value={
                "loop": MagicMock(),
                "memory": mock_memory,
                "settings": mock_settings,
            }):
                result = await web_ui.add_memory(mock_request)
                assert result["id"] == "new_id"

    @pytest.mark.asyncio
    async def test_delete_memory(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None

            mock_memory = MagicMock()
            mock_memory.storage = MagicMock()
            mock_memory.storage.delete = AsyncMock(return_value=MagicMock(is_ok=True))

            with patch.object(web_ui, "get_agent", return_value={
                "loop": MagicMock(),
                "memory": mock_memory,
                "settings": mock_settings,
            }):
                result = await web_ui.delete_memory("mem123")
                assert result["ok"] is True
