"""
单元测试 — 子 Agent 管理器 (src/execution/sub_agent_manager.py)

覆盖：
- SubAgentManager 初始化
- spawn() - 创建子 Agent
- wait() - 等待完成
- cancel() - 取消子 Agent
- 并发限制
- history / running_count 属性
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.execution.sub_agent_manager import (
    SubAgentManager,
    SubAgentStatus,
    SubAgentTask,
)


@pytest.fixture
def manager():
    return SubAgentManager()


@pytest.fixture
def manager_with_mock_tools():
    mock_tool_system = AsyncMock()
    mock_tool_system.execute = AsyncMock(return_value={"output": "done"})
    return SubAgentManager(
        tool_system=mock_tool_system,
        max_concurrent=3,
    )


class TestInit:
    def test_default_init(self):
        mgr = SubAgentManager()
        assert mgr.tool_system is None
        assert mgr.llm_fn is None
        assert mgr.approval_gate is None
        assert mgr.max_concurrent is None
        assert mgr._running == {}
        assert mgr._history == []

    def test_with_params(self):
        mock_ts = MagicMock()
        mock_llm = MagicMock()
        mock_ag = MagicMock()
        mgr = SubAgentManager(
            tool_system=mock_ts,
            llm_fn=mock_llm,
            approval_gate=mock_ag,
            max_concurrent=5,
        )
        assert mgr.tool_system is mock_ts
        assert mgr.llm_fn is mock_llm
        assert mgr.approval_gate is mock_ag
        assert mgr.max_concurrent == 5


class TestSpawn:
    @pytest.mark.asyncio
    async def test_spawn_creates_subagent(self, manager_with_mock_tools):
        task = SubAgentTask(description="test task", tool_name="echo")
        sa = await manager_with_mock_tools.spawn(task)
        assert sa is not None
        assert sa.id in manager_with_mock_tools._running
        # Cancel to clean up
        await manager_with_mock_tools.cancel(sa.id)

    @pytest.mark.asyncio
    async def test_spawn_exceeds_concurrency(self, manager_with_mock_tools):
        manager_with_mock_tools.max_concurrent = 1
        task1 = SubAgentTask(description="task1", tool_name="echo")
        task2 = SubAgentTask(description="task2", tool_name="echo")

        sa1 = await manager_with_mock_tools.spawn(task1)

        with pytest.raises(RuntimeError, match="超过最大并发数"):
            await manager_with_mock_tools.spawn(task2)

        await manager_with_mock_tools.cancel(sa1.id)

    @pytest.mark.asyncio
    async def test_spawn_without_tool_system(self, manager):
        task = SubAgentTask(description="no tool", tool_name="none")
        sa = await manager.spawn(task)
        # spawn sets status to RUNNING immediately
        assert sa.status == SubAgentStatus.RUNNING
        # _execute will change it to PENDING_CONFIRMATION async
        # Give it a moment to complete
        await asyncio.sleep(0.1)
        assert sa.status == SubAgentStatus.PENDING_CONFIRMATION


class TestWait:
    @pytest.mark.asyncio
    async def test_wait_nonexistent(self, manager):
        result = await manager.wait("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_completed(self, manager_with_mock_tools):
        task = SubAgentTask(description="quick task", tool_name="echo")
        sa = await manager_with_mock_tools.spawn(task)
        result = await manager_with_mock_tools.wait(sa.id, timeout=5)
        assert result is not None


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, manager):
        result = await manager.cancel("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_running(self, manager_with_mock_tools):
        task = SubAgentTask(description="cancel me", tool_name="echo")
        sa = await manager_with_mock_tools.spawn(task)
        result = await manager_with_mock_tools.cancel(sa.id)
        assert result is True
        assert sa.status == SubAgentStatus.CANCELLED
        assert sa.id not in manager_with_mock_tools._running
        assert sa in manager_with_mock_tools._history

    @pytest.mark.asyncio
    async def test_cancel_moves_to_history(self, manager_with_mock_tools):
        task = SubAgentTask(description="to history", tool_name="echo")
        sa = await manager_with_mock_tools.spawn(task)
        await manager_with_mock_tools.cancel(sa.id)
        assert len(manager_with_mock_tools.history) == 1


class TestProperties:
    @pytest.mark.asyncio
    async def test_running_count(self, manager_with_mock_tools):
        task = SubAgentTask(description="count me", tool_name="echo")
        sa = await manager_with_mock_tools.spawn(task)
        assert manager_with_mock_tools.running_count >= 1
        await manager_with_mock_tools.cancel(sa.id)

    def test_history_empty(self, manager):
        assert manager.history == []


class TestSubAgentTask:
    def test_task_defaults(self):
        task = SubAgentTask()
        assert task.description == ""
        assert task.tool_name == ""
        assert task.tool_params == {}
        assert task.timeout_seconds is None

    def test_task_custom(self):
        task = SubAgentTask(
            description="test",
            tool_name="shell",
            tool_params={"cmd": "ls"},
            timeout_seconds=60,
        )
        assert task.description == "test"
        assert task.tool_name == "shell"
        assert task.timeout_seconds == 60
