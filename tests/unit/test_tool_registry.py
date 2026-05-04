"""
ToolRegistry — 单元测试

覆盖：工具注册/执行/列表、三级沙箱、ToolResult
"""
import pytest

from src.execution.tool_registry import ToolLevel, ToolRegistry, ToolResult


@pytest.fixture
def registry():
    return ToolRegistry()


def _sync_handler(name):
    return lambda **kw: f"executed {name}"


def _async_handler(name):
    async def handler(**kw):
        return f"async executed {name}"
    return handler


def _failing_handler(**kw):
    raise RuntimeError("tool error")


class TestToolRegistryRegister:
    def test_register_tool(self, registry):
        registry.register("search", "搜索工具", ToolLevel.L1_SAFE, _sync_handler("search"))
        assert len(registry.list_tools()) == 1

    def test_register_multiple_tools(self, registry):
        for i in range(5):
            registry.register(f"tool_{i}", f"工具{i}", ToolLevel.L1_SAFE, _sync_handler(f"t{i}"))
        assert len(registry.list_tools()) == 5

    def test_list_tools_returns_dicts(self, registry):
        registry.register("read", "读文件", ToolLevel.L1_SAFE, _sync_handler("read"))
        tools = registry.list_tools()
        assert tools[0]["name"] == "read"
        assert tools[0]["level"] == "L1_SAFE"


class TestToolRegistryExecute:
    @pytest.mark.asyncio
    async def test_execute_l1_sync(self, registry):
        registry.register("echo", "回声", ToolLevel.L1_SAFE, _sync_handler("echo"))
        result = await registry.execute("echo", {"msg": "hello"})
        assert result.success is True
        assert "executed echo" in result.output

    @pytest.mark.asyncio
    async def test_execute_l2(self, registry):
        registry.register("write", "写文件", ToolLevel.L2_CONFIRM, _sync_handler("write"))
        result = await registry.execute("write", {"file": "test.txt"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_l3_needs_approval(self, registry):
        registry.register("delete", "删除", ToolLevel.L3_APPROVE, _sync_handler("delete"))
        result = await registry.execute("delete", {"file": "test.txt"})
        assert result.needs_approval is True

    @pytest.mark.asyncio
    async def test_execute_l3_with_callback(self, registry):
        from unittest.mock import AsyncMock
        registry.register("delete", "删除", ToolLevel.L3_APPROVE, _sync_handler("delete"))
        cb = AsyncMock(return_value=True)
        result = await registry.execute("delete", {"file": "test.txt"},
                                        approval_callback=cb)
        assert result.success is True
        cb.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_unregistered_tool(self, registry):
        result = await registry.execute("nonexistent", {})
        assert result.success is False
        assert "未注册" in result.error

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self, registry):
        registry.register("fail", "失败工具", ToolLevel.L1_SAFE, _failing_handler)
        result = await registry.execute("fail", {})
        assert result.success is False
        assert "tool error" in result.error


class TestToolResult:
    def test_success_result(self):
        r = ToolResult(True, "ok")
        assert r.success is True
        assert r.output == "ok"
        assert r.error == ""
        assert r.needs_approval is False

    def test_failure_result(self):
        r = ToolResult(False, "", "error msg")
        assert r.success is False
        assert r.error == "error msg"

    def test_approval_result(self):
        r = ToolResult(False, "", "needs approval", needs_approval=True)
        assert r.needs_approval is True
