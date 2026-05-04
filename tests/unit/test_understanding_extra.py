"""
理解引擎补充测试 — 提升 src/understanding/engine.py 覆盖率

覆盖：
- LLM 解析路径（_parse_by_llm）
- LLM 失败降级路径
- 规则匹配完整路径
- 追问生成
- 跑偏检查
- 意图关键词完整匹配
- 人格反馈规则
"""

import json
from unittest.mock import AsyncMock, MagicMock

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
            content=json.dumps({
                "type": "memory_write",
                "target_layer": "core",
                "confidence": 0.9,
                "requires_approval": False,
                "action": "记住",
                "target": "内容",
            })
        )
    )
    return UnderstandingEngine(llm_provider=llm)


class TestLLMParsePath:
    """测试 LLM 解析路径"""

    @pytest.mark.asyncio
    async def test_llm_parse_success(self, engine_with_llm):
        """LLM 解析成功"""
        intent = await engine_with_llm.parse("记住这个信息")
        assert intent.type == "memory_write"
        assert intent.target_layer == "core"
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_llm_parse_with_context(self, engine_with_llm):
        """LLM 解析带上下文"""
        context = {
            "relevant_memories": [
                {"content": "用户喜欢简洁回复"},
                {"content": "用户是开发者"},
            ]
        }
        intent = await engine_with_llm.parse("记住这个", context=context)
        assert intent is not None
        # 验证 LLM 被调用
        engine_with_llm._llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_parse_failure_falls_back_to_rules(self, engine_with_llm):
        """LLM 解析失败后抛异常（不再降级到规则）"""
        engine_with_llm._llm.chat = AsyncMock(
            return_value=LLMResult.fail(error="API 错误")
        )
        intent = await engine_with_llm.parse("记住这个")
        assert intent.type == "unknown"
        assert intent.needs_clarification is True

    @pytest.mark.asyncio
    async def test_llm_parse_invalid_json_falls_back(self, engine_with_llm):
        """LLM 返回无效 JSON 后返回 unknown + 追问"""
        engine_with_llm._llm.chat = AsyncMock(
            return_value=LLMResult.success(content="不是有效的 JSON")
        )
        intent = await engine_with_llm.parse("记住这个")
        assert intent.type == "unknown"
        assert intent.needs_clarification is True

    @pytest.mark.asyncio
    async def test_llm_parse_exception_falls_back(self, engine_with_llm):
        """LLM 抛出异常后抛 RuntimeError（LLM-only 原则）"""
        engine_with_llm._llm.chat = AsyncMock(side_effect=Exception("网络错误"))
        with pytest.raises(RuntimeError, match="LLM不可用"):
            await engine_with_llm.parse("记住这个")

    @pytest.mark.asyncio
    async def test_llm_parse_missing_fields(self, engine_with_llm):
        """LLM 返回缺少字段的 JSON"""
        engine_with_llm._llm.chat = AsyncMock(
            return_value=LLMResult.success(
                content=json.dumps({"type": "memory_read"})
            )
        )
        intent = await engine_with_llm.parse("搜索记忆")
        assert intent.type == "memory_read"


class TestLocalRulesComplete:
    """测试完整的本地规则匹配"""

    @pytest.mark.asyncio
    async def test_all_local_rules(self, engine_no_llm):
        """所有本地规则应正确匹配"""
        test_cases = {
            "停": "interrupt",
            "退出": "exit",
            "帮助": "help",
            "你是谁": "who_are_you",
            "现在几点": "current_time",
            "清空记忆": "clear_memory",
            "重置人格": "reset_personality",
            "查看记忆": "show_memory",
            "查看人格": "show_personality",
        }
        for input_text, expected_type in test_cases.items():
            intent = await engine_no_llm.parse(input_text)
            assert intent.type == expected_type, \
                f"输入 '{input_text}' 应匹配 '{expected_type}'，实际为 '{intent.type}'"

    @pytest.mark.asyncio
    async def test_local_rules_confidence_is_1(self, engine_no_llm):
        """本地规则匹配置信度应为 1.0"""
        intent = await engine_no_llm.parse("退出")
        assert intent.confidence == 1.0

    @pytest.mark.asyncio
    async def test_clear_memory_requires_approval(self, engine_no_llm):
        """清空记忆需要审批"""
        intent = await engine_no_llm.parse("清空记忆")
        assert intent.requires_approval is True

    @pytest.mark.asyncio
    async def test_reset_personality_requires_approval(self, engine_no_llm):
        """重置人格需要审批"""
        intent = await engine_no_llm.parse("重置人格")
        assert intent.requires_approval is True


class TestRuleFallbackComplete:
    """测试关键词兜底已移除 — 无LLM时应抛异常"""

    @pytest.mark.asyncio
    async def test_memory_write_all_keywords(self, engine_no_llm):
        """所有 memory_write 关键词不再走规则"""
        keywords = ["记住", "记录", "保存", "写入", "添加", "新建"]
        for kw in keywords:
            with pytest.raises(RuntimeError, match="LLM不可用"):
                await engine_no_llm.parse(f"{kw}这个")

    @pytest.mark.asyncio
    async def test_unknown_input(self, engine_no_llm):
        """未知输入无LLM应抛异常"""
        with pytest.raises(RuntimeError, match="LLM不可用"):
            await engine_no_llm.parse("随便说点什么")


class TestClarificationStrategy:
    """测试追问策略"""

    def test_clarification_result_default(self):
        """ClarificationResult 默认值"""
        r = ClarificationResult()
        assert r.question == ""
        assert r.original_input == ""
        assert r.attempts == 0
        assert r.max_attempts == 3

    def test_clarification_result_custom(self):
        """ClarificationResult 自定义值"""
        r = ClarificationResult(
            question="你想做什么？",
            original_input="test",
            attempts=1,
            max_attempts=5,
        )
        assert r.question == "你想做什么？"
        assert r.max_attempts == 5


class TestIntentDataClass:
    """测试 Intent 数据类"""

    def test_default_values(self):
        """默认值"""
        intent = Intent()
        assert intent.type == ""
        assert intent.content == ""
        assert intent.target_layer == "core"
        assert intent.confidence == 0.0
        assert intent.requires_approval is False
        assert intent.metadata == {}
        assert intent.needs_clarification is False
        assert intent.clarification_question == ""
        assert intent.clarification_strategy == "none"

    def test_custom_values(self):
        """自定义值"""
        intent = Intent(
            type="memory_write",
            content="test",
            target_layer="personality",
            confidence=0.8,
            requires_approval=True,
            metadata={"key": "value"},
            needs_clarification=True,
            clarification_question="请确认",
            clarification_strategy="confirm",
        )
        assert intent.type == "memory_write"
        assert intent.confidence == 0.8
        assert intent.requires_approval is True
        assert intent.metadata == {"key": "value"}


class TestPersonalityFeedback:
    """测试人格反馈分析（关键词规则已移除，仅走LLM）"""

    def test_analyze_personality_feedback_method(self):
        """analyze_personality_feedback 存在"""
        assert hasattr(UnderstandingEngine, 'analyze_personality_feedback')

    def test_analyze_by_llm_method(self):
        """_analyze_by_llm 存在，EMOTION 常量已移除"""
        assert hasattr(UnderstandingEngine, '_analyze_by_llm')
        assert not hasattr(UnderstandingEngine, 'EMOTION_POSITIVE')
        assert not hasattr(UnderstandingEngine, 'EMOTION_NEGATIVE')


class TestEngineProperties:
    """测试引擎属性"""

    def test_has_llm_property_no_llm(self):
        """无 LLM 时 has_llm 为 False"""
        engine = UnderstandingEngine(llm_provider=None)
        assert engine.has_llm is False

    def test_has_llm_property_with_llm(self):
        """有 LLM 时 has_llm 为 True"""
        llm = MagicMock()
        engine = UnderstandingEngine(llm_provider=llm)
        assert engine.has_llm is True

    def test_should_call_llm_for_unknown_input(self):
        """未知输入应调用 LLM"""
        engine = UnderstandingEngine(llm_provider=MagicMock())
        assert engine.should_call_llm("未知输入") is True

    def test_should_call_llm_for_local_rule(self):
        """should_call_llm 始终返回 True（不再区分本地规则）"""
        engine = UnderstandingEngine(llm_provider=MagicMock())
        assert engine.should_call_llm("退出") is True
        assert engine.should_call_llm("帮助") is True
        assert engine.should_call_llm("任意输入") is True
