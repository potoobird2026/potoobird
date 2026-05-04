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

# web_ui 依赖 fastapi，可选安装
try:
    from fastapi import FastAPI, Request  # noqa: F401
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def _make_mock_settings(tmp_path):
    s = MagicMock()
    s.log_level = "INFO"
    s.log_file = str(tmp_path / "agent.log")
    s.database_path = str(tmp_path / "memory.db")
    s.data_dir = str(tmp_path)
    s.openai_api_key = ""
    s.openai_model = "gpt-4o"
    return s


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
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


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestRoutes:
    def test_app_exists(self):
        from src.entry import web_ui
        assert hasattr(web_ui, "app")
        assert isinstance(web_ui.app, FastAPI)

    def test_static_mount(self):
        from src.entry import web_ui
        paths = [r.path for r in web_ui.app.routes]
        assert any("/static" in p for p in paths)


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestIndexRoute:
    @pytest.mark.asyncio
    async def test_index_returns_html(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            request = MagicMock()
            response = await web_ui.index(request)
            assert response is not None


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestChatRoute:
    @pytest.mark.asyncio
    async def test_chat_success(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        mock_loop = MagicMock()
        mock_loop.run = AsyncMock(return_value="回复内容")
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"message": "你好"})

        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            with patch.object(web_ui, "get_agent", return_value={
                "loop": mock_loop,
                "memory": MagicMock(),
                "settings": mock_settings,
            }):
                result = await web_ui.chat(mock_request)
                assert "response" in result
                assert result["response"] == "回复内容"

    @pytest.mark.asyncio
    async def test_chat_error(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        mock_loop = MagicMock()
        mock_loop.run = AsyncMock(side_effect=Exception("LLM error"))
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"message": "test"})

        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
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
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={})

        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            with patch.object(web_ui, "get_agent", return_value={
                "loop": MagicMock(),
                "memory": MagicMock(),
                "settings": mock_settings,
            }):
                result = await web_ui.chat(mock_request)
                assert "response" in result


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestMemoryRoutes:
    @pytest.mark.asyncio
    async def test_get_memories(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            with patch.object(web_ui, "get_agent") as mock_get_agent:
                mock_memory = MagicMock()
                mock_memory.search = AsyncMock(return_value=[])
                mock_get_agent.return_value = {
                    "loop": MagicMock(),
                    "memory": mock_memory,
                    "settings": mock_settings,
                }
                result = await web_ui.get_memories()
                assert "memories" in result

    @pytest.mark.asyncio
    async def test_add_memory(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={"content": "新记忆", "layer": "core"})

        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            with patch.object(web_ui, "get_agent") as mock_get_agent:
                mock_memory = MagicMock()
                mock_memory.remember = AsyncMock()
                mock_get_agent.return_value = {
                    "loop": MagicMock(),
                    "memory": mock_memory,
                    "settings": mock_settings,
                }
                result = await web_ui.add_memory(mock_request)
                assert result is not None

    @pytest.mark.asyncio
    async def test_delete_memory(self, tmp_path):
        mock_settings = _make_mock_settings(tmp_path)
        with patch("src.entry.web_ui.Settings", return_value=mock_settings), \
             patch("src.entry.web_ui.init_logging"):
            from src.entry import web_ui
            web_ui._agent = None
            with patch.object(web_ui, "get_agent") as mock_get_agent:
                mock_memory = MagicMock()
                mock_memory.storage.delete = AsyncMock()
                mock_get_agent.return_value = {
                    "loop": MagicMock(),
                    "memory": mock_memory,
                    "settings": mock_settings,
                }
                result = await web_ui.delete_memory("mem-001")
                assert result is not None
