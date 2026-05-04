"""
单元测试 — UnderstandingEngine
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.understanding.engine import Intent, UnderstandingEngine


@pytest.fixture
def engine():
    return UnderstandingEngine()


# ---- should_call_llm ----


def test_should_call_llm_always_true(engine):
    """should_call_llm 始终返回 True，强制走 LLM"""
    assert engine.should_call_llm("退出") is True
    assert engine.should_call_llm("帮助") is True
    assert engine.should_call_llm("清空记忆") is True
    assert engine.should_call_llm("重置人格") is True
    assert engine.should_call_llm("查看记忆") is True
    assert engine.should_call_llm("查看人格") is True
    assert engine.should_call_llm("停") is True
    assert engine.should_call_llm("你是谁") is True
    assert engine.should_call_llm("现在几点") is True
    assert engine.should_call_llm("帮我分析一下这个项目") is True
    assert engine.should_call_llm("") is True


# ---- parse 意图（无 LLM 时回退固定模板，不抛异常）----


@pytest.mark.asyncio
async def test_parse_memory_write_fallback(engine):
    """LLM不可用时抛 RuntimeError（LLM-only 原则）"""
    with pytest.raises(RuntimeError, match="LLM不可用"):
        await engine.parse("记住 Python 的用法")


@pytest.mark.asyncio
async def test_parse_memory_read_fallback(engine):
    """LLM不可用时抛 RuntimeError（LLM-only 原则）"""
    with pytest.raises(RuntimeError, match="LLM不可用"):
        await engine.parse("查看我的记忆")


@pytest.mark.asyncio
async def test_parse_memory_search_fallback(engine):
    with pytest.raises(RuntimeError, match="LLM不可用"):
        await engine.parse("搜索 Python 相关内容")


@pytest.mark.asyncio
async def test_parse_personality_update_fallback(engine):
    with pytest.raises(RuntimeError, match="LLM不可用"):
        await engine.parse("你应该更简洁")


@pytest.mark.asyncio
async def test_parse_unknown_fallback(engine):
    with pytest.raises(RuntimeError, match="LLM不可用"):
        await engine.parse("asdfghjkl")


@pytest.mark.asyncio
async def test_parse_exit_works_without_llm(engine):
    """退出 是 LOCAL_RULES 系统命令，不需要 LLM"""
    intent = await engine.parse("退出")
    assert intent.type == "exit"


@pytest.mark.asyncio
async def test_parse_clear_memory_works_without_llm(engine):
    """清空记忆 是 LOCAL_RULES 系统命令，不需要 LLM"""
    intent = await engine.parse("清空记忆")
    assert intent.requires_approval is True


@pytest.mark.asyncio
async def test_parse_reset_personality_works_without_llm(engine):
    """重置人格 是 LOCAL_RULES 系统命令，不需要 LLM"""
    intent = await engine.parse("重置人格")
    assert intent.requires_approval is True


@pytest.mark.asyncio
async def test_parse_vague_fallback(engine):
    with pytest.raises(RuntimeError, match="LLM不可用"):
        await engine.parse("嗯")


# ---- generate_clarification ----


@pytest.mark.asyncio
async def test_clarification_question(engine):
    # mock LLM 返回
    fake_llm = AsyncMock()
    fake_llm.chat = AsyncMock(
        return_value=MagicMock(
            is_ok=True, content='{"question": "你想做什么？请具体说明。", "strategy": "open"}'
        )
    )
    engine._llm = fake_llm
    intent = Intent(type="unknown", content="模糊", confidence=0.2)
    result = await engine.generate_clarification("模糊", intent, attempt=1)
    assert len(result.question) > 0
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_clarification_increments_attempts(engine):
    fake_llm = AsyncMock()
    fake_llm.chat = AsyncMock(
        return_value=MagicMock(is_ok=True, content='{"question": "请详细说说", "strategy": "open"}')
    )
    engine._llm = fake_llm
    intent = Intent(type="unknown", content="还是模糊", confidence=0.3)
    r1 = await engine.generate_clarification("模糊1", intent, attempt=1)
    r2 = await engine.generate_clarification("模糊2", intent, attempt=2)
    assert r1.attempts == 1
    assert r2.attempts == 2


@pytest.mark.asyncio
async def test_clarification_max_attempts(engine):
    fake_llm = AsyncMock()
    fake_llm.chat = AsyncMock(
        return_value=MagicMock(
            is_ok=True, content='{"question": "请描述具体需求", "strategy": "confirm"}'
        )
    )
    engine._llm = fake_llm
    intent = Intent(type="unknown", content="持续模糊", confidence=0.1)
    result = await engine.generate_clarification("模糊", intent, attempt=3)
    assert result.attempts == 3
