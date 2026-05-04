"""
理解层测试
"""

import pytest

from src.understanding.engine import UnderstandingEngine


@pytest.fixture
def engine():
    return UnderstandingEngine()


class TestLocalRules:
    """LOCAL_RULES 作为系统命令（退出/帮助等），不需要LLM"""

    @pytest.mark.asyncio
    async def test_exit_command_works_without_llm(self, engine):
        intent = await engine.parse("退出")
        assert intent.type == "exit"

    @pytest.mark.asyncio
    async def test_help_command_works_without_llm(self, engine):
        intent = await engine.parse("帮助")
        assert intent.type == "help"

    @pytest.mark.asyncio
    async def test_clear_memory_without_llm(self, engine):
        intent = await engine.parse("清空记忆")
        assert intent.requires_approval is True

    @pytest.mark.asyncio
    async def test_reset_personality_without_llm(self, engine):
        intent = await engine.parse("重置人格")
        assert intent.requires_approval is True



class TestIntentParsing:
    """非 LOCAL_RULES 输入，无 LLM 时抛 RuntimeError（LLM-only）"""

    @pytest.mark.asyncio
    async def test_memory_write_raises_without_llm(self, engine):
        with pytest.raises(RuntimeError, match="LLM不可用"):
            await engine.parse("记住 Python 的用法")

    @pytest.mark.asyncio
    async def test_unknown_input_raises_without_llm(self, engine):
        with pytest.raises(RuntimeError, match="LLM不可用"):
            await engine.parse("asdfghjkl")


class TestShouldCallLLM:
    def test_always_true(self, engine):
        """should_call_llm 始终返回 True"""
        assert engine.should_call_llm("退出") is True
        assert engine.should_call_llm("帮助") is True
        assert engine.should_call_llm("请帮我分析一下这段代码") is True


class TestClarification:
    """generate_clarification — 无 LLM 时抛 RuntimeError，有 LLM 时异步生成追问"""

    @pytest.mark.asyncio
    async def test_no_llm_raises(self, engine):
        """无 LLM 时 generate_clarification 抛出 RuntimeError"""
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        with pytest.raises(RuntimeError, match="LLM不可用"):
            await engine.generate_clarification("模糊输入", intent, attempt=1)

    @pytest.mark.asyncio
    async def test_with_llm_returns_question(self):
        """有 LLM 时返回追问结果"""
        from unittest.mock import AsyncMock
        from src.errors.types import LLMResult
        from src.understanding.engine import Intent, UnderstandingEngine
        llm = AsyncMock()
        llm.chat = AsyncMock(
            return_value=LLMResult.success(
                content='{"question": "你想让我做什么？", "strategy": "open"}'
            )
        )
        engine_with_llm = UnderstandingEngine(llm_provider=llm)
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = await engine_with_llm.generate_clarification("模糊输入", intent, attempt=1)
        assert result.question == "你想让我做什么？"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_with_llm_by_llm_directly(self):
        """直接调用 generate_clarification_by_llm"""
        from unittest.mock import AsyncMock
        from src.errors.types import LLMResult
        from src.understanding.engine import Intent, UnderstandingEngine
        llm = AsyncMock()
        llm.chat = AsyncMock(
            return_value=LLMResult.success(
                content='{"question": "请具体说明", "strategy": "confirm"}'
            )
        )
        engine_with_llm = UnderstandingEngine(llm_provider=llm)
        intent = Intent(type="unknown", content="test", confidence=0.2)
        result = await engine_with_llm.generate_clarification_by_llm("test", intent, attempt=2)
        assert result.question == "请具体说明"
        assert result.attempts == 2

    @pytest.mark.asyncio
    async def test_llm_failure_raises(self):
        """LLM 返回失败时抛出 RuntimeError"""
        from unittest.mock import AsyncMock
        from src.errors.types import LLMResult
        from src.understanding.engine import Intent, UnderstandingEngine
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=LLMResult.fail(error="API 错误"))
        engine_with_llm = UnderstandingEngine(llm_provider=llm)
        intent = Intent(type="unknown", content="test", confidence=0.2)
        with pytest.raises(RuntimeError, match="LLM 追问生成失败"):
            await engine_with_llm.generate_clarification("test", intent, attempt=1)
