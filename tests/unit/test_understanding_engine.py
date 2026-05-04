"""
理解引擎 — 补充单元测试

覆盖：
- 本地规则路径
- 规则降级路径
- LLM 解析路径
- 追问生成
- 跑偏检查
"""

from unittest.mock import AsyncMock

import pytest

from src.errors.types import LLMResult
from src.understanding.engine import ClarificationResult, Intent, UnderstandingEngine


@pytest.fixture
def engine_no_llm():
    """无 LLM 的理解引擎"""
    return UnderstandingEngine(llm_provider=None)


@pytest.fixture
def engine_with_llm():
    """有 LLM 的理解引擎"""
    llm = AsyncMock()
    llm.chat = AsyncMock(
        return_value=LLMResult.success(
            content='{"type": "memory_write", "target_layer": "core", '
            '"confidence": 0.9, "requires_approval": false, '
            '"action": "记住", "target": "内容"}'
        )
    )
    return UnderstandingEngine(llm_provider=llm)


class TestLocalRules:
    """测试本地规则（精确匹配 LOCAL_RULES 表）"""

    @pytest.mark.asyncio
    async def test_exit_rule(self, engine_no_llm):
        intent = await engine_no_llm.parse("退出")
        assert intent.type == "exit"
        assert intent.confidence == 1.0

    @pytest.mark.asyncio
    async def test_help_rule(self, engine_no_llm):
        intent = await engine_no_llm.parse("帮助")
        assert intent.type == "help"

    @pytest.mark.asyncio
    async def test_who_are_you_rule(self, engine_no_llm):
        intent = await engine_no_llm.parse("你是谁")
        assert intent.type == "who_are_you"

    @pytest.mark.asyncio
    async def test_clear_memory_requires_approval(self, engine_no_llm):
        intent = await engine_no_llm.parse("清空记忆")
        assert intent.requires_approval is True

    @pytest.mark.asyncio
    async def test_reset_personality_requires_approval(self, engine_no_llm):
        intent = await engine_no_llm.parse("重置人格")
        assert intent.requires_approval is True


class TestRuleFallback:
    """测试规则降级路径 — 无LLM时回退固定模板，不抛异常"""

    @pytest.mark.asyncio
    async def test_no_llm_fallback_template(self, engine_no_llm):
        """无LLM时抛 RuntimeError（LLM-only 原则）"""
        with pytest.raises(RuntimeError, match="LLM不可用"):
            await engine_no_llm.parse("记住这个")

    @pytest.mark.asyncio
    async def test_memory_read_keywords(self, engine_no_llm):
        # "查看记忆" 在 LOCAL_RULES 中精确匹配为 show_memory
        intent = await engine_no_llm.parse("查看记忆")
        assert intent.type == "show_memory"


class TestLlmPath:
    """测试 LLM 解析路径"""

    @pytest.mark.asyncio
    async def test_llm_parse_success(self, engine_with_llm):
        intent = await engine_with_llm.parse("记住这个")
        assert intent.type == "memory_write"
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_llm_parse_failure_returns_unknown(self, engine_with_llm):
        """LLM 返回非 JSON 时返回 unknown + 追问"""
        engine_with_llm._llm.chat = AsyncMock(
            return_value=LLMResult.success(content="不是 JSON")
        )
        intent = await engine_with_llm.parse("记住这个")
        assert intent.type == "unknown"
        assert intent.needs_clarification is True

    @pytest.mark.asyncio
    async def test_llm_exception_raises_error(self, engine_with_llm):
        """LLM 异常时抛 RuntimeError（LLM-only 原则）"""
        engine_with_llm._llm.chat = AsyncMock(side_effect=RuntimeError("API 错误"))
        with pytest.raises(RuntimeError, match="LLM不可用"):
            await engine_with_llm.parse("记住这个")


class TestShouldCallLlm:
    """测试 should_call_llm"""

    def test_always_returns_true(self, engine_no_llm):
        """should_call_llm 始终返回 True"""
        assert engine_no_llm.should_call_llm("退出") is True
        assert engine_no_llm.should_call_llm("帮助") is True
        assert engine_no_llm.should_call_llm("你是谁") is True
        assert engine_no_llm.should_call_llm("任意输入") is True


class TestClarification:
    """测试追问生成"""

    @pytest.mark.asyncio
    async def test_generate_clarification(self, engine_no_llm):
        # mock LLM
        from unittest.mock import AsyncMock, MagicMock
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value=MagicMock(
            is_ok=True,
            content='{"question": "你想做什么？", "strategy": "open"}'
        ))
        engine_no_llm._llm = fake_llm
        intent = Intent(type="llm_chat", confidence=0.2)
        result = await engine_no_llm.generate_clarification("模糊输入", intent, attempt=1)
        assert isinstance(result, ClarificationResult)
        assert len(result.question) > 0
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_clarification_max_attempts(self, engine_no_llm):
        from unittest.mock import AsyncMock, MagicMock
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value=MagicMock(
            is_ok=True,
            content='{"question": "请详细描述", "strategy": "open"}'
        ))
        engine_no_llm._llm = fake_llm
        intent = Intent(type="llm_chat", confidence=0.2)
        result = await engine_no_llm.generate_clarification("模糊输入", intent, attempt=5)
        assert result.attempts == 5


class TestIsOffTrack:
    """测试跑偏检查"""

    def test_empty_result(self, engine_no_llm):
        """空结果不判定跑偏（保守策略）"""
        assert engine_no_llm.is_off_track("", Intent(type="memory_write")) is False

    def test_none_result(self, engine_no_llm):
        """None 结果不判定跑偏（保守策略）"""
        assert engine_no_llm.is_off_track(None, Intent(type="memory_write")) is False

    def test_memory_write_with_confirm(self, engine_no_llm):
        """包含确认关键词 → 不跑偏"""
        assert engine_no_llm.is_off_track("已记住", Intent(type="memory_write")) is False

    def test_memory_write_long_reply(self, engine_no_llm):
        """长回复 → 不轻易判定跑偏"""
        long_reply = "好的，我已经记住了这个信息，你可以随时问我"
        assert engine_no_llm.is_off_track(long_reply, Intent(type="memory_write")) is False

    def test_default_not_off_track(self, engine_no_llm):
        """默认不判定跑偏（保守策略）"""
        assert engine_no_llm.is_off_track("普通回复", Intent(type="llm_chat")) is False
