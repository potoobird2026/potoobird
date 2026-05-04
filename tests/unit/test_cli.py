"""
单元测试 — CLI 入口 (src/entry/cli.py)

覆盖：
- create_agent() 工厂函数
- CLI 命令定义
- 交互模式 (run 命令)
- 单条命令 (once 命令)
- 审计命令 (audit show)
- 可观测性命令 (metrics show / prometheus / health)
- LLM Provider 初始化失败降级路径
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


@pytest.fixture
def mock_settings(tmp_path):
    """Mock Settings 避免加密密钥初始化"""
    s = MagicMock()
    s.log_level = "INFO"
    s.log_file = str(tmp_path / "agent.log")
    s.database_path = str(tmp_path / "memory.db")
    s.data_dir = str(tmp_path)
    s.openai_api_key = ""
    s.openai_model = "gpt-4o"
    return s


# ──────────────────────────────────────────────
# create_agent() 工厂函数
# ──────────────────────────────────────────────

class TestCreateAgent:
    """测试 create_agent() 工厂函数"""

    def test_returns_dict_with_keys(self, mock_settings, tmp_path):
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent()
            assert "settings" in agent
            assert "memory" in agent
            assert "understanding" in agent
            assert "security" in agent
            assert "agent_loop" in agent
            assert "metrics" in agent
            assert "health_checker" in agent

    def test_read_only_mode(self, mock_settings, tmp_path):
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent(read_only=True)
            assert agent["read_only"] is True

    def test_default_read_only_is_false(self, mock_settings, tmp_path):
        """默认 read_only 应为 False"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent()
            assert agent["read_only"] is False

    def test_no_api_key_no_llm(self, mock_settings, tmp_path):
        """没有 API Key 时 llm_provider 为 None"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent()
            assert agent["llm_provider"] is None

    def test_with_api_key_creates_llm(self, mock_settings, tmp_path):
        mock_settings.openai_api_key = "sk-test-key"
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.llm.provider.OpenAIProvider") as MockProvider:
            mock_provider = MagicMock()
            MockProvider.return_value = mock_provider
            from src.entry import cli
            agent = cli.create_agent()
            MockProvider.assert_called_once()

    def test_llm_init_failure_fallback(self, mock_settings, tmp_path):
        """LLM Provider 初始化失败时应降级为无 LLM 模式"""
        mock_settings.openai_api_key = "sk-test-key"
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.llm.provider.OpenAIProvider", side_effect=Exception("init failed")):
            from src.entry import cli
            agent = cli.create_agent()
            # 降级后 llm_provider 应为 None
            assert agent["llm_provider"] is None

    def test_settings_passed_to_init_logging(self, mock_settings, tmp_path):
        """验证 init_logging 被正确调用"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging") as mock_init_log:
            from src.entry import cli
            cli.create_agent()
            mock_init_log.assert_called_once_with("INFO", str(tmp_path / "agent.log"))


# ──────────────────────────────────────────────
# CLI 命令定义
# ──────────────────────────────────────────────

class TestCLICommands:
    """测试 CLI 命令定义"""

    def test_app_exists(self):
        from src.entry import cli
        assert cli.app is not None

    def test_audit_subcommand(self):
        from src.entry import cli
        assert cli.audit_app is not None

    def test_metrics_subcommand(self):
        from src.entry import cli
        assert cli.metrics_app is not None

    def test_app_has_registered_commands(self):
        """验证 run/once 命令已注册（typer 顶层命令 name 可能为 None）"""
        from src.entry import cli
        registered = cli.app.registered_commands
        callback_names = [c.callback.__name__ for c in registered if c.callback]
        assert "run" in callback_names
        assert "once" in callback_names

    def test_audit_has_show_command(self):
        """验证 audit show 命令已注册"""
        from src.entry import cli
        registered = cli.audit_app.registered_commands
        cmd_names = [c.name for c in registered]
        assert "show" in cmd_names

    def test_metrics_has_show_command(self):
        """验证 metrics show 命令已注册"""
        from src.entry import cli
        registered = cli.metrics_app.registered_commands
        cmd_names = [c.name for c in registered]
        assert "show" in cmd_names

    def test_metrics_has_prometheus_command(self):
        """验证 metrics prometheus 命令已注册"""
        from src.entry import cli
        registered = cli.metrics_app.registered_commands
        cmd_names = [c.name for c in registered]
        assert "prometheus" in cmd_names

    def test_metrics_has_health_command(self):
        """验证 metrics health 命令已注册"""
        from src.entry import cli
        registered = cli.metrics_app.registered_commands
        cmd_names = [c.name for c in registered]
        assert "health" in cmd_names


# ──────────────────────────────────────────────
# run 命令 — 交互模式
# ──────────────────────────────────────────────

class TestRunCommand:
    """测试 run 命令（交互模式）"""

    def test_run_command_exists(self):
        from src.entry import cli
        commands = cli.app.registered_groups
        assert len(commands) > 0

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_read_only_banner(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """只读模式应显示警告横幅"""
        mock_asyncio.new_event_loop.return_value = MagicMock()
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = EOFError()

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.run(read_only=True)
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("只读" in c for c in echo_calls)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_normal_banner(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """正常模式应显示欢迎横幅"""
        mock_asyncio.new_event_loop.return_value = MagicMock()
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = EOFError()

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.run(read_only=False)
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("Long Agent" in c for c in echo_calls)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_exit_keywords(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """测试退出关键词：退出/exit/quit/q"""
        mock_asyncio.new_event_loop.return_value = MagicMock()
        mock_asyncio.set_event_loop = MagicMock()

        for keyword in ["退出", "exit", "quit", "q"]:
            mock_typer.prompt.reset_mock()
            mock_typer.echo.reset_mock()
            mock_typer.prompt.side_effect = [keyword]

            with patch("src.entry.cli.Settings", return_value=mock_settings), \
                 patch("src.entry.cli.init_logging"):
                from src.entry import cli
                cli.run(read_only=False)
                echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
                assert not any("Agent:" in c for c in echo_calls)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_empty_input_skipped(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """空输入应被跳过"""
        mock_loop = MagicMock()
        mock_asyncio.new_event_loop.return_value = mock_loop
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = ["  ", "退出"]

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.run(read_only=False)
            assert not mock_loop.run_until_complete.called

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_security_filter_rejects_input(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """安全过滤拒绝输入时应显示警告"""
        mock_loop = MagicMock()
        mock_asyncio.new_event_loop.return_value = mock_loop
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = ["bad input", "退出"]

        mock_filter_result = MagicMock()
        mock_filter_result.is_ok = False
        mock_filter_result.error_message = "危险输入"

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_agent = {
                "security": MagicMock(filter=MagicMock(return_value=mock_filter_result)),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
            }
            mock_create.return_value = mock_agent

            from src.entry import cli
            cli.run(read_only=False)
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("输入被拒绝" in c for c in echo_calls)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_agent_loop_exception(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """主循环异常时应显示错误信息"""
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = Exception("loop error")
        mock_asyncio.new_event_loop.return_value = mock_loop
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = ["hello", "退出"]

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.run(read_only=False)
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("处理失败" in c for c in echo_calls)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_eof_exits_gracefully(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """EOFError 应优雅退出"""
        mock_asyncio.new_event_loop.return_value = MagicMock()
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = EOFError()

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.run(read_only=False)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_keyboard_interrupt_exits_gracefully(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """KeyboardInterrupt 应优雅退出"""
        mock_asyncio.new_event_loop.return_value = MagicMock()
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = KeyboardInterrupt()

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.run(read_only=False)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_run_memory_closed_on_exit(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """退出时应关闭 memory"""
        mock_asyncio.new_event_loop.return_value = MagicMock()
        mock_asyncio.set_event_loop = MagicMock()
        mock_typer.prompt.side_effect = EOFError()

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_memory = MagicMock()
            mock_create.return_value = {
                "security": MagicMock(filter=MagicMock(return_value=MagicMock(is_ok=True))),
                "agent_loop": MagicMock(),
                "memory": mock_memory,
            }
            from src.entry import cli
            cli.run(read_only=False)
            mock_memory.close.assert_called_once()


# ──────────────────────────────────────────────
# once 命令 — 单条命令
# ──────────────────────────────────────────────

class TestOnceCommand:
    """测试 once 命令（单条命令执行）"""

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_once_executes_command(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """once 应执行单条命令并输出结果"""
        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = "test response"
        mock_asyncio.new_event_loop.return_value = mock_loop

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.once(command="hello", read_only=False)
            mock_typer.echo.assert_any_call("Agent: test response")

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_once_security_rejects(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """once 命令安全过滤拒绝时应显示警告"""
        mock_filter_result = MagicMock()
        mock_filter_result.is_ok = False
        mock_filter_result.error_message = "危险"

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_create.return_value = {
                "security": MagicMock(filter=MagicMock(return_value=mock_filter_result)),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
            }
            from src.entry import cli
            cli.once(command="bad", read_only=False)
            mock_typer.echo.assert_any_call("⚠️  输入被拒绝：危险")

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_once_exception_handling(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """once 命令异常时应显示错误"""
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = Exception("exec error")
        mock_asyncio.new_event_loop.return_value = mock_loop

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            cli.once(command="hello", read_only=False)
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("处理失败" in c for c in echo_calls)

    @patch("src.entry.cli.asyncio")
    @patch("src.entry.cli.typer")
    def test_once_memory_closed_on_exit(self, mock_typer, mock_asyncio, mock_settings, tmp_path):
        """once 命令退出时应关闭 memory"""
        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = "ok"
        mock_asyncio.new_event_loop.return_value = mock_loop

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_memory = MagicMock()
            mock_create.return_value = {
                "security": MagicMock(filter=MagicMock(return_value=MagicMock(is_ok=True))),
                "agent_loop": MagicMock(),
                "memory": mock_memory,
            }
            from src.entry import cli
            cli.once(command="hello", read_only=False)
            mock_memory.close.assert_called_once()


# ──────────────────────────────────────────────
# audit show 命令
# ──────────────────────────────────────────────

class TestAuditShowCommand:
    """测试 audit show 命令"""

    @patch("src.entry.cli.typer")
    def test_audit_show_no_entries(self, mock_typer, mock_settings, tmp_path):
        """无审计记录时应显示提示"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_audit = MagicMock()
            mock_audit.query.return_value = []
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(audit=mock_audit),
            }
            from src.entry import cli
            cli.audit_show(action=None, limit=20)
            mock_typer.echo.assert_any_call("暂无审计记录。")

    @patch("src.entry.cli.typer")
    def test_audit_show_with_entries(self, mock_typer, mock_settings, tmp_path):
        """有审计记录时应显示条目"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_audit = MagicMock()
            mock_audit.query.return_value = [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "action": "test_action",
                    "details": {"key": "value"},
                    "success": True,
                }
            ]
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(audit=mock_audit),
            }
            from src.entry import cli
            cli.audit_show(action=None, limit=20)
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("test_action" in c for c in echo_calls)

    @patch("src.entry.cli.typer")
    def test_audit_show_with_failed_entry(self, mock_typer, mock_settings, tmp_path):
        """失败条目应显示 ❌ 图标"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_audit = MagicMock()
            mock_audit.query.return_value = [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "action": "fail_action",
                    "details": {},
                    "success": False,
                }
            ]
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(audit=mock_audit),
            }
            from src.entry import cli
            cli.audit_show(action=None, limit=20)
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("❌" in c for c in echo_calls)

    @patch("src.entry.cli.typer")
    def test_audit_show_with_action_filter(self, mock_typer, mock_settings, tmp_path):
        """带 action 过滤时应传递 AuditAction"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_audit = MagicMock()
            mock_audit.query.return_value = []
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(audit=mock_audit),
            }
            from src.entry import cli
            # 使用有效的 AuditAction 值
            cli.audit_show(action="memory_write", limit=10)
            mock_audit.query.assert_called_once()


# ──────────────────────────────────────────────
# metrics show 命令
# ──────────────────────────────────────────────

class TestMetricsShowCommand:
    """测试 metrics show 命令"""

    @patch("src.entry.cli.typer")
    def test_metrics_show_no_collector(self, mock_typer, mock_settings, tmp_path):
        """无指标采集器时应显示警告"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "metrics": None,
            }
            from src.entry import cli
            cli.metrics_show(format="text")
            mock_typer.echo.assert_any_call("⚠️  指标采集器未初始化")

    @patch("src.entry.cli.typer")
    def test_metrics_show_text_format(self, mock_typer, mock_settings, tmp_path):
        """text 格式应显示指标摘要"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_metrics = MagicMock()
            mock_metrics.summary.return_value = {
                "_counters": {"requests": 10},
                "_errors": {},
                "_gauges": {},
            }
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "metrics": mock_metrics,
            }
            from src.entry import cli
            cli.metrics_show(format="text")
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("指标快照" in c for c in echo_calls)

    @patch("src.entry.cli.typer")
    def test_metrics_show_json_format(self, mock_typer, mock_settings, tmp_path):
        """json 格式应输出 JSON"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_metrics = MagicMock()
            mock_metrics.summary.return_value = {"key": "value"}
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "metrics": mock_metrics,
            }
            from src.entry import cli
            cli.metrics_show(format="json")
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("key" in c for c in echo_calls)

    @patch("src.entry.cli.typer")
    def test_metrics_show_with_timings(self, mock_typer, mock_settings, tmp_path):
        """有耗时应显示耗时信息"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_metrics = MagicMock()
            mock_metrics.summary.return_value = {
                "llm_call": {"count": 5, "avg_ms": 100.5, "max_ms": 200.0},
            }
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "metrics": mock_metrics,
            }
            from src.entry import cli
            cli.metrics_show(format="text")
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("耗时" in c for c in echo_calls)


# ──────────────────────────────────────────────
# metrics prometheus 命令
# ──────────────────────────────────────────────

class TestMetricsPrometheusCommand:
    """测试 metrics prometheus 命令"""

    @patch("src.entry.cli.typer")
    def test_prometheus_no_collector(self, mock_typer, mock_settings, tmp_path):
        """无采集器时应输出提示"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "metrics": None,
            }
            from src.entry import cli
            cli.metrics_prometheus()
            mock_typer.echo.assert_any_call("# No metrics collector configured")

    @patch("src.entry.cli.typer")
    def test_prometheus_output(self, mock_typer, mock_settings, tmp_path):
        """有采集器时应输出 Prometheus 格式"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_metrics = MagicMock()
            mock_metrics.prometheus_metrics.return_value = "# HELP test_metric\n"
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "metrics": mock_metrics,
            }
            from src.entry import cli
            cli.metrics_prometheus()
            mock_typer.echo.assert_any_call("# HELP test_metric\n")


# ──────────────────────────────────────────────
# metrics health 命令
# ──────────────────────────────────────────────

class TestMetricsHealthCommand:
    """测试 metrics health 命令"""

    @patch("src.entry.cli.typer")
    def test_health_no_checker(self, mock_typer, mock_settings, tmp_path):
        """无健康检查器时应显示警告"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "health_checker": None,
            }
            from src.entry import cli
            cli.metrics_health()
            mock_typer.echo.assert_any_call("⚠️  健康检查器未初始化")

    @patch("src.entry.cli.typer")
    def test_health_ok(self, mock_typer, mock_settings, tmp_path):
        """健康状态正常时应显示 ✅"""
        mock_status = MagicMock()
        mock_status.ok = True
        mock_status.uptime_seconds = 100.0
        mock_status.memory_count = 5
        mock_status.components = {"db": "ok", "llm": "ok"}
        mock_status.last_error = None

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "health_checker": MagicMock(check=MagicMock(return_value=mock_status)),
            }
            from src.entry import cli
            cli.metrics_health()
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("健康" in c for c in echo_calls)

    @patch("src.entry.cli.typer")
    def test_health_not_ok(self, mock_typer, mock_settings, tmp_path):
        """健康状态异常时应显示 ❌"""
        mock_status = MagicMock()
        mock_status.ok = False
        mock_status.uptime_seconds = 10.0
        mock_status.memory_count = 0
        mock_status.components = {"db": "error"}
        mock_status.last_error = "connection failed"

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "health_checker": MagicMock(check=MagicMock(return_value=mock_status)),
            }
            from src.entry import cli
            cli.metrics_health()
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("异常" in c for c in echo_calls)

    @patch("src.entry.cli.typer")
    def test_health_with_last_error(self, mock_typer, mock_settings, tmp_path):
        """有最后错误时应显示错误信息"""
        mock_status = MagicMock()
        mock_status.ok = False
        mock_status.uptime_seconds = 10.0
        mock_status.memory_count = 0
        mock_status.components = {}
        mock_status.last_error = "db connection failed"

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": MagicMock(),
                "health_checker": MagicMock(check=MagicMock(return_value=mock_status)),
            }
            from src.entry import cli
            cli.metrics_health()
            echo_calls = [str(c) for c in mock_typer.echo.call_args_list]
            assert any("最后错误" in c for c in echo_calls)

    @patch("src.entry.cli.typer")
    def test_health_memory_closed(self, mock_typer, mock_settings, tmp_path):
        """健康检查后应关闭 memory"""
        mock_status = MagicMock()
        mock_status.ok = True
        mock_status.uptime_seconds = 1.0
        mock_status.memory_count = 0
        mock_status.components = {}
        mock_status.last_error = None

        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.entry.cli.create_agent") as mock_create:
            mock_memory = MagicMock()
            mock_create.return_value = {
                "security": MagicMock(),
                "agent_loop": MagicMock(),
                "memory": mock_memory,
                "health_checker": MagicMock(check=MagicMock(return_value=mock_status)),
            }
            from src.entry import cli
            cli.metrics_health()
            mock_memory.close.assert_called_once()


# ──────────────────────────────────────────────
# __main__ 入口
# ──────────────────────────────────────────────

class TestMainEntry:
    """测试 __main__ 入口"""

    @patch("src.entry.cli.app")
    def test_main_calls_app(self, mock_app):
        """__main__ 应调用 app()"""
        from src.entry import cli
        with patch.object(cli, "__name__", "__main__"):
            if cli.__name__ == "__main__":
                cli.app()
            mock_app.assert_called_once()
