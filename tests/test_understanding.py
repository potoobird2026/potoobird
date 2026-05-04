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
    """generate_clarification 直接构造 Intent，不经过 parse()"""

    def test_first_attempt(self, engine):
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=1)
        assert "你想让我做什么" in result.question
        assert result.attempts == 1

    def test_max_attempts_capped(self, engine):
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=5)
        assert result.attempts == 5
        # 追问文案不应超出数组范围
        assert result.question != ""

    def test_personality_none_no_change(self, engine):
        """personality=None 时不调整语气"""
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=1, personality=None)
        assert "你想让我做什么" in result.question

    def test_personality_high_X_adds_tone(self, engine):
        """X > 70 外向性：添加主动语气词"""
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=1, personality={"X": 80, "A": 50, "E": 50})
        assert "怎么样" in result.question or "吧" in result.question

    def test_personality_high_A_adds_polite(self, engine):
        """A > 70 宜人性：添加敬语"""
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=1, personality={"X": 50, "A": 80, "E": 50})
        assert "请" in result.question

    def test_personality_high_E_adds_warmth(self, engine):
        """E > 70 情绪性：添加温度词/表情"""
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=1, personality={"X": 50, "A": 50, "E": 80})
        assert "😊" in result.question

    def test_personality_low_E_neutral(self, engine):
        """E < 30 情绪性：保持客观中立，无表情"""
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=1, personality={"X": 50, "A": 50, "E": 20})
        assert "😊" not in result.question

    def test_personality_low_A_direct(self, engine):
        """A < 30 宜人性：语气直接，不用敬语"""
        from src.understanding.engine import Intent
        intent = Intent(type="llm_chat", content="模糊输入", confidence=0.3)
        result = engine.generate_clarification("模糊输入", intent, attempt=1, personality={"X": 50, "A": 20, "E": 50})
        assert "请" not in result.question
