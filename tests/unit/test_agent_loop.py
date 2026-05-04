"""
Agent 主循环 — 单元测试

覆盖：状态机转换、7步循环、错误恢复、追问、审批、跑偏重试、各执行路径
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.errors.types import ErrorCode, LLMResult
from src.loop.agent_loop import AgentLoop, LoopContext
from src.loop.state import AgentState

# ---- Helpers ----

def _make_intent(
    intent_type="llm_chat",
    confidence=0.8,
    requires_approval=False,
    needs_clarification=False,
    clarification_question="",
    target_layer="core",
    metadata=None,
):
    return MagicMock(
        type=intent_type,
        content="test",
        confidence=confidence,
        requires_approval=requires_approval,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question,
        target_layer=target_layer,
        metadata=metadata or {},
    )


def _go_to(state_machine, target: AgentState):
    """按合法路径转换到目标状态"""
    path = [
        AgentState.IDLE,
        AgentState.PERCEIVING,
        AgentState.UNDERSTANDING,
        AgentState.PLANNING,
        AgentState.EXECUTING,
        AgentState.OBSERVING,
        AgentState.REFLECTING,
        AgentState.REPLYING,
        AgentState.IDLE,
    ]
    if target in path:
        idx = path.index(target)
        for i in range(1, idx + 1):
            try:
                state_machine.transition_to(path[i])
            except Exception:
                pass


@pytest.fixture
def mock_memory():
    memory = AsyncMock()
    memory.remember = AsyncMock(
        return_value=MagicMock(id="mem-001", created=True, message="已记住")
    )
    memory.search = AsyncMock(return_value=[])
    memory.get_personality = MagicMock(
        return_value={"H": 50, "E": 50, "X": 50, "A": 50, "C": 50, "O": 50}
    )
    # 显式禁用 V2 方法，让现有测试走 V1 路径
    memory.load_memORIES_for_context = None
    memory.check_and_evict = None
    return memory


@pytest.fixture
def mock_understanding():
    u = AsyncMock()
    u.parse = AsyncMock(return_value=_make_intent())
    u.is_off_track = MagicMock(return_value=False)
    return u


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=LLMResult.success(content="LLM 回复"))
    llm.model = "gpt-4o"
    return llm


@pytest.fixture
def agent_loop(mock_memory, mock_understanding, mock_llm):
    return AgentLoop(
        memory_manager=mock_memory,
        understanding_engine=mock_understanding,
        llm_provider=mock_llm,
        tool_system=None,
        audit_logger=None,
    )


@pytest.fixture
def agent_loop_no_llm(mock_memory, mock_understanding):
    return AgentLoop(
        memory_manager=mock_memory,
        understanding_engine=mock_understanding,
        llm_provider=None,
        tool_system=None,
        audit_logger=None,
    )


# ---- Tests ----

class TestInit:
    def test_without_llm(self, agent_loop_no_llm):
        assert agent_loop_no_llm.state == AgentState.IDLE
        assert agent_loop_no_llm.llm is None

    def test_with_llm(self, agent_loop):
        assert agent_loop.llm is not None
        assert agent_loop.memory is not None


class TestStateTransitions:
    def test_initial(self, agent_loop):
        assert agent_loop.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_perceive(self, agent_loop):
        await agent_loop._step_perceive(LoopContext(user_input="hi"))
        # 步骤方法不再做状态转换，状态由 run() 管理
        assert agent_loop.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_understand(self, agent_loop):
        _go_to(agent_loop._state_machine, AgentState.PERCEIVING)
        await agent_loop._step_understand(LoopContext(user_input="hi"))
        # 步骤方法不再做状态转换，状态保持 _go_to 设置的值
        assert agent_loop.state == AgentState.PERCEIVING

    @pytest.mark.asyncio
    async def test_plan(self, agent_loop):
        _go_to(agent_loop._state_machine, AgentState.UNDERSTANDING)
        await agent_loop._step_plan(LoopContext(user_input="hi"))
        assert agent_loop.state == AgentState.UNDERSTANDING

    @pytest.mark.asyncio
    async def test_observe(self, agent_loop):
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        ctx = LoopContext(user_input="hi")
        ctx.execution_result = "result"
        await agent_loop._step_observe(ctx)
        assert agent_loop.state == AgentState.EXECUTING

    @pytest.mark.asyncio
    async def test_reflect(self, agent_loop):
        _go_to(agent_loop._state_machine, AgentState.OBSERVING)
        await agent_loop._step_reflect(LoopContext(user_input="hi"))
        assert agent_loop.state == AgentState.OBSERVING

    @pytest.mark.asyncio
    async def test_reply(self, agent_loop):
        _go_to(agent_loop._state_machine, AgentState.REFLECTING)
        ctx = LoopContext(user_input="hi")
        ctx.execution_result = "result"
        await agent_loop._step_reply(ctx)
        # 步骤方法不再做状态转换
        assert agent_loop.state == AgentState.REFLECTING
        assert ctx.response == "result"


class TestFullRun:
    @pytest.mark.asyncio
    async def test_basic(self, agent_loop):
        resp = await agent_loop.run("你好")
        assert isinstance(resp, str)
        assert len(resp) > 0

    @pytest.mark.asyncio
    async def test_local_rule_exit(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(intent_type="exit", confidence=1.0)
        )
        resp = await agent_loop.run("退出")
        assert isinstance(resp, str)

    @pytest.mark.asyncio
    async def test_memory_write(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(intent_type="memory_write", target_layer="core")
        )
        resp = await agent_loop.run("记住这个")
        assert isinstance(resp, str)
        assert len(resp) > 0

    @pytest.mark.asyncio
    async def test_memory_read(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(intent_type="memory_read")
        )
        resp = await agent_loop.run("查看记忆")
        assert isinstance(resp, str)

    @pytest.mark.asyncio
    async def test_memory_search(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(intent_type="memory_search")
        )
        resp = await agent_loop.run("搜索记忆")
        assert isinstance(resp, str)

    @pytest.mark.asyncio
    async def test_no_llm(self, agent_loop_no_llm, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(intent_type="llm_chat", confidence=0.5)
        )
        resp = await agent_loop_no_llm.run("你好")
        assert isinstance(resp, str)
        assert len(resp) > 0

    @pytest.mark.asyncio
    async def test_llm_failure(self, agent_loop, mock_llm, mock_understanding):
        mock_llm.chat = AsyncMock(
            return_value=LLMResult.fail(error="超时", code=ErrorCode.CONNECTION_ERROR)
        )
        resp = await agent_loop.run("你好")
        assert isinstance(resp, str)


class TestClarification:
    @pytest.mark.asyncio
    async def test_needs_clarification(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(
                needs_clarification=True,
                clarification_question="你想做什么？",
            )
        )
        mock_understanding.has_llm = True
        from src.understanding.engine import ClarificationResult
        mock_understanding.generate_clarification_by_llm = AsyncMock(
            return_value=ClarificationResult(question="你想做什么？请具体说明。")
        )
        resp = await agent_loop.run("模糊")
        # 返回追问问题（字符串或 ClarificationResult）
        if isinstance(resp, str):
            assert len(resp) > 0
        else:
            assert hasattr(resp, 'question')
            assert len(resp.question) > 0


class TestApproval:
    @pytest.mark.asyncio
    async def test_requires_approval(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(
                intent_type="clear_memory",
                requires_approval=True,
            )
        )
        resp = await agent_loop.run("清空记忆")
        assert "等待审批" in resp


class TestOffTrackRetry:
    @pytest.mark.asyncio
    async def test_retry_on_off_track(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(intent_type="llm_chat")
        )
        mock_understanding.is_off_track = MagicMock(side_effect=[True, False])
        resp = await agent_loop.run("测试")
        assert isinstance(resp, str)

    @pytest.mark.asyncio
    async def test_max_retries(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(
            return_value=_make_intent(intent_type="llm_chat")
        )
        mock_understanding.is_off_track = MagicMock(return_value=True)
        resp = await agent_loop.run("测试")
        assert isinstance(resp, str)


class TestStop:
    @pytest.mark.asyncio
    async def test_stop(self, agent_loop):
        agent_loop._running = True
        await agent_loop.stop()
        assert agent_loop._running is False


class TestLoopContext:
    def test_defaults(self):
        ctx = LoopContext()
        assert ctx.user_input == ""
        assert ctx.error == ""
        assert ctx.retry_count == 0
        assert ctx.is_off_track is False

    def test_loop_id(self):
        ctx = LoopContext()
        assert len(ctx.loop_id) == 8


class TestExecutePaths:
    @pytest.mark.asyncio
    async def test_write_no_memory(self, agent_loop):
        agent_loop.memory = None
        ctx = LoopContext(user_input="记住")
        ctx.filtered_input = "记住"
        ctx.intent = _make_intent(target_layer="core")
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._execute_memory_write(ctx)
        assert ctx.execution_result == "记忆系统未初始化"

    @pytest.mark.asyncio
    async def test_read_no_memory(self, agent_loop):
        agent_loop.memory = None
        ctx = LoopContext(user_input="查看")
        ctx.filtered_input = "查看"
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._execute_memory_read(ctx)
        assert ctx.execution_result == "记忆系统未初始化"

    @pytest.mark.asyncio
    async def test_read_with_results(self, agent_loop, mock_memory):
        mock_memory.search = AsyncMock(
            return_value=[
                MagicMock(content="记忆1", category="general", layer="core"),
            ]
        )
        ctx = LoopContext(user_input="搜索")
        ctx.filtered_input = "搜索"
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._execute_memory_read(ctx)
        assert "找到以下记忆" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_read_no_results(self, agent_loop, mock_memory):
        mock_memory.search = AsyncMock(return_value=[])
        ctx = LoopContext(user_input="搜索")
        ctx.filtered_input = "搜索"
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._execute_memory_read(ctx)
        assert "没有找到" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_tool_no_tools(self, agent_loop):
        ctx = LoopContext(user_input="调用工具")
        ctx.filtered_input = "调用工具"
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._execute_tool_call(ctx)
        assert ctx.execution_result == "工具系统未初始化"

    @pytest.mark.asyncio
    async def test_llm_no_llm(self, agent_loop_no_llm):
        ctx = LoopContext(user_input="你好")
        ctx.filtered_input = "你好"
        _go_to(agent_loop_no_llm._state_machine, AgentState.EXECUTING)
        await agent_loop_no_llm._execute_llm_chat(ctx)
        assert "LLM 未初始化" in ctx.execution_result

    @pytest.mark.asyncio
    async def test_llm_success(self, agent_loop, mock_llm):
        mock_llm.chat = AsyncMock(
            return_value=LLMResult.success(content="回复内容")
        )
        ctx = LoopContext(user_input="你好")
        ctx.filtered_input = "你好"
        ctx.memory_context = {"personality": {}, "relevant_memories": []}
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._execute_llm_chat(ctx)
        assert ctx.execution_result == "回复内容"

    @pytest.mark.asyncio
    async def test_llm_failure(self, agent_loop, mock_llm):
        mock_llm.chat = AsyncMock(
            return_value=LLMResult.fail(error="API 错误", code=ErrorCode.SERVER_ERROR)
        )
        ctx = LoopContext(user_input="你好")
        ctx.filtered_input = "你好"
        ctx.memory_context = {"personality": {}, "relevant_memories": []}
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._execute_llm_chat(ctx)
        assert "LLM 调用失败" in ctx.execution_result


class TestObserve:
    @pytest.mark.asyncio
    async def test_empty_result(self, agent_loop):
        ctx = LoopContext(user_input="t")
        ctx.execution_result = ""
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._step_observe(ctx)
        assert ctx.is_off_track is True

    @pytest.mark.asyncio
    async def test_normal(self, agent_loop):
        ctx = LoopContext(user_input="t")
        ctx.execution_result = "ok"
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._step_observe(ctx)
        assert ctx.is_off_track is False

    @pytest.mark.asyncio
    async def test_no_engine(self, agent_loop):
        agent_loop.understanding = None
        ctx = LoopContext(user_input="t")
        ctx.execution_result = "ok"
        _go_to(agent_loop._state_machine, AgentState.EXECUTING)
        await agent_loop._step_observe(ctx)
        assert ctx.is_off_track is False


class TestReflect:
    @pytest.mark.asyncio
    async def test_with_audit(self, agent_loop):
        agent_loop.audit = AsyncMock()
        _go_to(agent_loop._state_machine, AgentState.OBSERVING)
        await agent_loop._step_reflect(LoopContext(user_input="t"))
        agent_loop.audit.log.assert_called_once()

    @pytest.mark.asyncio
    async def test_without_audit(self, agent_loop):
        agent_loop.audit = None
        _go_to(agent_loop._state_machine, AgentState.OBSERVING)
        await agent_loop._step_reflect(LoopContext(user_input="t"))
        assert True  # 不抛异常


class TestReply:
    @pytest.mark.asyncio
    async def test_with_result(self, agent_loop):
        ctx = LoopContext(user_input="t")
        ctx.execution_result = "结果"
        _go_to(agent_loop._state_machine, AgentState.REFLECTING)
        await agent_loop._step_reply(ctx)
        assert ctx.response == "结果"
        # 步骤方法不再做状态转换
        assert agent_loop.state == AgentState.REFLECTING

    @pytest.mark.asyncio
    async def test_with_llm(self, agent_loop):
        ctx = LoopContext(user_input="t")
        ctx.llm_result = LLMResult.success(content="LLM 回复")
        _go_to(agent_loop._state_machine, AgentState.REFLECTING)
        await agent_loop._step_reply(ctx)
        assert ctx.response == "LLM 回复"

    @pytest.mark.asyncio
    async def test_fallback(self, agent_loop):
        ctx = LoopContext(user_input="t")
        _go_to(agent_loop._state_machine, AgentState.REFLECTING)
        await agent_loop._step_reply(ctx)
        assert "没有" in ctx.response or "合适" in ctx.response


class TestException:
    @pytest.mark.asyncio
    async def test_exception_handled(self, agent_loop, mock_understanding):
        mock_understanding.parse = AsyncMock(side_effect=RuntimeError("test"))
        resp = await agent_loop.run("触发异常")
        # 意图解析异常后降级到 unknown，然后走 llm_chat 路径
        # 只要不抛异常、返回字符串即可
        assert isinstance(resp, str)
        assert len(resp) > 0


class TestLoadMemory:
    @pytest.mark.asyncio
    async def test_load_all(self, agent_loop, mock_memory):
        """_step_perceive 调用记忆加载"""
        agent_loop._running = True  # 绕过停止信号检查
        mock_memory.get_personality = MagicMock(return_value={"H": 60})
        mock_memory.get_standards = MagicMock(return_value=[])
        mock_memory.search = AsyncMock(return_value=[])
        ctx = LoopContext(user_input="t")
        ctx.filtered_input = "t"
        await agent_loop._step_perceive(ctx)
        # 验证记忆加载方法被调用
        mock_memory.get_personality.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_exception(self, agent_loop, mock_memory):
        """记忆加载异常时不影响感知阶段"""
        agent_loop._running = True  # 绕过停止信号检查
        mock_memory.get_personality = MagicMock(side_effect=IOError("损坏"))
        mock_memory.get_standards = MagicMock(return_value=[])
        mock_memory.search = AsyncMock(return_value=[])
        ctx = LoopContext(user_input="t")
        ctx.filtered_input = "t"
        await agent_loop._step_perceive(ctx)
        # 步骤方法不再做状态转换，状态保持初始值
        assert agent_loop.state == AgentState.IDLE
