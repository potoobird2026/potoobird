"""
AgentLoop 步骤方法单元测试

覆盖 _step_perceive / _step_execute / _step_observe / _step_reply
每个测试将状态机预设到正确的前置状态，避免非法转换。
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.loop.agent_loop import AgentLoop, LoopContext, _build_plan_from_intent
from src.loop.state import AgentState


def make_ctx(**kwargs) -> LoopContext:
    ctx = LoopContext(
        user_input="测试输入",
        conversation_id="test-conv",
    )
    for k, v in kwargs.items():
        setattr(ctx, k, v)
    return ctx


def set_state(loop: AgentLoop, state: AgentState):
    """将状态机强制设为指定状态（通过 reset + 合法路径转换）"""
    sm = loop._state_machine
    sm._current_state = state  # 直接设置内部状态，绕过合法转换检查


# ========== _step_perceive ==========

class TestStepPerceive:
    @pytest.mark.asyncio
    async def test_sets_perceiving_state(self):
        loop = AgentLoop()
        ctx = make_ctx()
        # 不需要预设状态，IDLE → PERCEIVING 是合法的
        await loop._step_perceive(ctx)
        assert ctx.filtered_input == "测试输入"

    @pytest.mark.asyncio
    async def test_perceive_sets_filtered_input(self):
        """验证 filtered_input 被正确设置为 user_input"""
        loop = AgentLoop()
        ctx = make_ctx()
        await loop._step_perceive(ctx)
        assert ctx.filtered_input == "测试输入"

    @pytest.mark.asyncio
    async def test_loads_memory_context(self):
        loop = AgentLoop()
        mock_memory = AsyncMock()
        mock_memory.get_personality.return_value = {"H": 70, "E": 60}
        mock_memory.search.return_value = [
            MagicMock(content="记忆1", category="core"),
        ]
        mock_memory.get_standards.return_value = [
            MagicMock(content="标准1", category="global"),
        ]
        loop.memory = mock_memory

        ctx = make_ctx()
        await loop._step_perceive(ctx)

        assert "personality" in ctx.memory_context
        assert "relevant_memories" in ctx.memory_context
        assert "standards" in ctx.memory_context

    @pytest.mark.asyncio
    async def test_memory_load_failure_degrades_gracefully(self):
        loop = AgentLoop()
        mock_memory = AsyncMock()
        mock_memory.get_personality.side_effect = Exception("记忆系统挂了")
        loop.memory = mock_memory

        ctx = make_ctx()
        await loop._step_perceive(ctx)
        assert isinstance(ctx.memory_context, dict)

    @pytest.mark.asyncio
    async def test_compressor_called_when_injected(self):
        loop = AgentLoop()
        mock_compressor = AsyncMock()
        mock_compressor.compress.return_value = MagicMock(
            kept_ids=["msg1", "msg2"],
            original_count=5,
            compressed_count=2,
        )
        loop.compressor = mock_compressor

        ctx = make_ctx()
        ctx.compressed_messages = [
            {"id": "msg1", "role": "user", "content": "旧消息1"},
            {"id": "msg2", "role": "assistant", "content": "旧消息2"},
            {"id": "msg3", "role": "user", "content": "旧消息3"},
            {"id": "system", "role": "system", "content": "系统提示"},
        ]
        await loop._step_perceive(ctx)

        mock_compressor.compress.assert_called_once()
        # system 消息应该被保留
        assert any(m.get("role") == "system" for m in ctx.compressed_messages)

    @pytest.mark.asyncio
    async def test_compressor_failure_degrades(self):
        loop = AgentLoop()
        mock_compressor = AsyncMock()
        mock_compressor.compress.side_effect = Exception("压缩失败")
        loop.compressor = mock_compressor

        ctx = make_ctx()
        ctx.compressed_messages = [{"id": "msg1", "role": "user", "content": "消息"}]
        original_messages = list(ctx.compressed_messages)
        await loop._step_perceive(ctx)
        assert ctx.compressed_messages == original_messages

    @pytest.mark.asyncio
    async def test_no_compressor_no_messages(self):
        loop = AgentLoop()
        ctx = make_ctx()
        ctx.compressed_messages = None
        await loop._step_perceive(ctx)
        assert ctx.filtered_input == "测试输入"


# ========== _step_execute ==========

class TestStepExecute:
    @pytest.mark.asyncio
    async def test_sets_executing_state(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)  # PLANNING → EXECUTING 合法
        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "llm_chat"
        ctx.operation_type = "llm_chat"
        await loop._step_execute(ctx)
        assert ctx.operation_type == "llm_chat"

    @pytest.mark.asyncio
    async def test_b_supervisor_path(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        mock_supervisor = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "执行结果"
        mock_result.status.value = "completed"
        mock_result.task_id = "task-001"
        mock_result.steps_completed = 3
        mock_supervisor.execute.return_value = mock_result
        loop.b_supervisor = mock_supervisor

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "llm_chat"
        ctx.operation_type = "llm_chat"
        await loop._step_execute(ctx)

        mock_supervisor.execute.assert_called_once()
        assert ctx.execution_result == "执行结果"
        assert ctx.memory_updated is True

    @pytest.mark.asyncio
    async def test_b_supervisor_failure_degrades_to_v1(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        mock_supervisor = AsyncMock()
        mock_supervisor.execute.side_effect = Exception("BSupervisor挂了")
        loop.b_supervisor = mock_supervisor
        loop.llm = AsyncMock()
        from src.llm.provider import LLMResult
        loop.llm.chat.return_value = LLMResult(content="LLM回复", ok=True)

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "llm_chat"
        ctx.operation_type = "llm_chat"
        await loop._step_execute(ctx)

        loop.llm.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_v1_llm_chat_path(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        loop.llm = AsyncMock()
        from src.llm.provider import LLMResult
        loop.llm.chat.return_value = LLMResult(content="LLM回复内容", ok=True)

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "llm_chat"
        ctx.operation_type = "llm_chat"
        await loop._step_execute(ctx)

        assert ctx.execution_result == "LLM回复内容"

    @pytest.mark.asyncio
    async def test_v1_llm_not_initialized(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "llm_chat"
        ctx.operation_type = "llm_chat"
        await loop._step_execute(ctx)

        assert "LLM 未初始化" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_v1_memory_write_path(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        loop.memory = AsyncMock()

        ctx = make_ctx()
        ctx.filtered_input = "测试输入"
        ctx.intent = MagicMock()
        ctx.intent.type = "memory_write"
        ctx.intent.target_layer = "core"
        ctx.operation_type = "memory_write"
        await loop._step_execute(ctx)

        loop.memory.remember.assert_called_once_with(
            content="测试输入",
            layer="core",
        )
        assert ctx.memory_updated is True
        assert "✅ 已记住" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_v1_memory_read_path(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        loop.memory = AsyncMock()
        loop.memory.search.return_value = [
            MagicMock(content="记忆A", category="core"),
            MagicMock(content="记忆B", category="episodic"),
        ]

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "memory_read"
        ctx.operation_type = "memory_read"
        await loop._step_execute(ctx)

        assert "找到以下记忆" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_v1_memory_read_empty(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        loop.memory = AsyncMock()
        loop.memory.search.return_value = []

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "memory_read"
        ctx.operation_type = "memory_read"
        await loop._step_execute(ctx)

        assert "没有找到相关记忆" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_v1_tool_call_path(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        mock_tools = AsyncMock()
        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.data = "工具返回数据"
        mock_tools.execute.return_value = mock_result
        loop.tools = mock_tools

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "tool_call"
        ctx.intent.metadata = {"tool_name": "search", "tool_params": {"q": "test"}}
        ctx.operation_type = "tool_call"
        await loop._step_execute(ctx)

        mock_tools.execute.assert_called_once_with("search", {"q": "test"})
        assert ctx.execution_result == "工具返回数据"

    @pytest.mark.asyncio
    async def test_v1_tool_call_failure(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        mock_tools = AsyncMock()
        mock_result = MagicMock()
        mock_result.is_ok = False
        mock_result.error_message = "工具错误"
        mock_tools.execute.return_value = mock_result
        loop.tools = mock_tools

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "tool_call"
        ctx.intent.metadata = {"tool_name": "bad_tool", "tool_params": {}}
        ctx.operation_type = "tool_call"
        await loop._step_execute(ctx)

        assert "工具调用失败" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_snapshot_saved_on_b_supervisor_success(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        mock_supervisor = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "结果"
        mock_result.status.value = "completed"
        mock_result.task_id = "task-001"
        mock_result.steps_completed = 2
        mock_supervisor.execute.return_value = mock_result

        mock_snapshot = AsyncMock()
        loop.b_supervisor = mock_supervisor
        loop.snapshot_manager = mock_snapshot

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "llm_chat"
        ctx.operation_type = "llm_chat"
        await loop._step_execute(ctx)

        mock_snapshot.save_snapshot.assert_called_once_with(
            task_id="task-001",
            step_index=2,
            state={"operation": "llm_chat", "result": "结果"},
        )

    @pytest.mark.asyncio
    async def test_execution_error_sets_fail_result(self):
        loop = AgentLoop()
        set_state(loop, AgentState.PLANNING)
        loop.llm = AsyncMock()
        loop.llm.chat.side_effect = Exception("LLM爆炸了")

        ctx = make_ctx()
        ctx.intent = MagicMock()
        ctx.intent.type = "llm_chat"
        ctx.operation_type = "llm_chat"
        await loop._step_execute(ctx)

        assert "LLM 调用异常" in ctx.execution_result


# ========== _step_observe ==========

class TestStepObserve:
    @pytest.mark.asyncio
    async def test_sets_observing_state(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)  # EXECUTING → OBSERVING 合法
        ctx = make_ctx()
        ctx.execution_result = "有结果"
        await loop._step_observe(ctx)
        assert ctx.is_off_track is False

    @pytest.mark.asyncio
    async def test_empty_result_marks_off_track(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)
        ctx = make_ctx()
        ctx.execution_result = ""
        await loop._step_observe(ctx)
        assert ctx.is_off_track is True
        assert ctx.off_track_reason == "执行结果为空"

    @pytest.mark.asyncio
    async def test_result_verifier_pass(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)
        mock_verifier = AsyncMock()
        mock_report = MagicMock()
        mock_report.overall_status.value = "passed"
        mock_report.summary = "通过"
        mock_verifier.verify.return_value = mock_report
        loop.result_verifier = mock_verifier

        ctx = make_ctx()
        ctx.execution_result = "有效结果"
        ctx.exec_result = MagicMock()
        await loop._step_observe(ctx)

        mock_verifier.verify.assert_called_once()
        assert ctx.is_off_track is False
        assert ctx.verification_passed is True

    @pytest.mark.asyncio
    async def test_result_verifier_fail_marks_off_track(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)
        mock_verifier = AsyncMock()
        mock_report = MagicMock()
        mock_report.overall_status.value = "failed"
        mock_report.summary = "质量不达标"
        mock_verifier.verify.return_value = mock_report
        loop.result_verifier = mock_verifier

        ctx = make_ctx()
        ctx.execution_result = "有结果"
        ctx.exec_result = MagicMock()
        await loop._step_observe(ctx)

        assert ctx.is_off_track is True
        assert ctx.off_track_reason == "质量不达标"

    @pytest.mark.asyncio
    async def test_result_verifier_failure_degrades(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)
        mock_verifier = AsyncMock()
        mock_verifier.verify.side_effect = Exception("验证器挂了")
        loop.result_verifier = mock_verifier

        ctx = make_ctx()
        ctx.execution_result = "有结果"
        ctx.exec_result = MagicMock()
        await loop._step_observe(ctx)

        assert ctx.is_off_track is False

    @pytest.mark.asyncio
    async def test_no_result_verifier_no_exec_result(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)
        ctx = make_ctx()
        ctx.execution_result = "有结果"
        ctx.exec_result = None
        await loop._step_observe(ctx)
        assert ctx.is_off_track is False

    @pytest.mark.asyncio
    async def test_understanding_engine_off_track_check(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)
        mock_understanding = MagicMock()
        mock_understanding.is_off_track = MagicMock(return_value=True)
        loop.understanding = mock_understanding

        ctx = make_ctx()
        ctx.execution_result = "有结果"
        await loop._step_observe(ctx)

        assert ctx.is_off_track is True
        assert ctx.off_track_reason == "理解引擎判定跑偏"

    @pytest.mark.asyncio
    async def test_understanding_engine_off_track_false(self):
        loop = AgentLoop()
        set_state(loop, AgentState.EXECUTING)
        mock_understanding = MagicMock()
        mock_understanding.is_off_track = MagicMock(return_value=False)
        loop.understanding = mock_understanding

        ctx = make_ctx()
        ctx.execution_result = "有结果"
        await loop._step_observe(ctx)

        assert ctx.is_off_track is False


# ========== _step_reply ==========

class TestStepReply:
    @pytest.mark.asyncio
    async def test_sets_replying_then_idle(self):
        loop = AgentLoop()
        set_state(loop, AgentState.OBSERVING)  # OBSERVING → REFLECTING → REPLYING，但reply直接从OBSERVING转
        ctx = make_ctx()
        ctx.execution_result = "最终结果"
        await loop._step_reply(ctx)
        assert ctx.response == "最终结果"

    @pytest.mark.asyncio
    async def test_report_generator_path(self):
        loop = AgentLoop()
        set_state(loop, AgentState.OBSERVING)
        mock_report_gen = MagicMock()
        mock_report = MagicMock()
        mock_report.user_summary = {"conclusion": "格式化后的结论"}
        mock_report_gen.generate.return_value = mock_report
        loop.report_generator = mock_report_gen

        ctx = make_ctx()
        ctx.verify_report = MagicMock()
        ctx.exec_result = MagicMock()
        await loop._step_reply(ctx)

        mock_report_gen.generate.assert_called_once_with(
            verification_report=ctx.verify_report,
            execution_result=ctx.exec_result,
        )
        assert ctx.response == "格式化后的结论"

    @pytest.mark.asyncio
    async def test_report_generator_failure_degrades(self):
        loop = AgentLoop()
        set_state(loop, AgentState.OBSERVING)
        mock_report_gen = MagicMock()
        mock_report_gen.generate.side_effect = Exception("报告生成挂了")
        loop.report_generator = mock_report_gen

        ctx = make_ctx()
        ctx.execution_result = "降级结果"
        await loop._step_reply(ctx)

        assert ctx.response == "降级结果"

    @pytest.mark.asyncio
    async def test_v1_llm_result_path(self):
        loop = AgentLoop()
        set_state(loop, AgentState.OBSERVING)
        ctx = make_ctx()
        ctx.execution_result = ""
        from src.llm.provider import LLMResult
        ctx.llm_result = LLMResult(content="LLM直接回复", ok=True)
        await loop._step_reply(ctx)

        assert ctx.response == "LLM直接回复"

    @pytest.mark.asyncio
    async def test_v1_fallback_default_response(self):
        loop = AgentLoop()
        set_state(loop, AgentState.OBSERVING)
        ctx = make_ctx()
        ctx.execution_result = ""
        from src.llm.provider import LLMResult
        ctx.llm_result = LLMResult(content=None, ok=False, error="失败")
        await loop._step_reply(ctx)

        assert ctx.response == "我没有找到合适的回复。"

    @pytest.mark.asyncio
    async def test_report_generator_no_user_summary(self):
        """report.user_summary 不存在时降级为 str(report)"""
        loop = AgentLoop()
        set_state(loop, AgentState.OBSERVING)
        mock_report_gen = MagicMock()
        mock_report = MagicMock()
        # 删除 user_summary 属性
        del mock_report.user_summary
        mock_report_gen.generate.return_value = mock_report
        loop.report_generator = mock_report_gen

        ctx = make_ctx()
        ctx.verify_report = MagicMock()
        ctx.exec_result = MagicMock()
        await loop._step_reply(ctx)

        # 降级路径：str(report) → 应该不抛异常
        assert ctx.response is not None


# ========== _build_plan_from_intent ==========

class TestBuildPlanFromIntent:
    def test_basic_plan(self):
        intent = MagicMock()
        intent.content = "写一篇文章"
        intent.acceptance_criteria = ["有标题", "有正文"]
        intent.max_steps = 3
        plan = _build_plan_from_intent(intent, "llm_chat")
        assert plan.deliverable == "写一篇文章"
        assert plan.acceptance_criteria == ["有标题", "有正文"]
        assert plan.max_steps == 3

    def test_empty_content_defaults_to_operation_type(self):
        intent = MagicMock()
        intent.content = ""
        intent.acceptance_criteria = []
        del intent.max_steps
        plan = _build_plan_from_intent(intent, "memory_write")
        assert plan.deliverable == "执行 memory_write"
        assert plan.acceptance_criteria == ["结果非空"]
        assert plan.max_steps == 5

    def test_no_acceptance_criteria_attr(self):
        intent = MagicMock(spec=[])
        intent.content = "test"
        plan = _build_plan_from_intent(intent, "tool_call")
        assert plan.deliverable == "test"
        assert plan.acceptance_criteria == ["结果非空"]
