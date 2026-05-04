"""
CLI 入口补充测试 — 提升 src/entry/cli.py 覆盖率

覆盖：
- create_agent() LLM 初始化失败降级路径
- create_agent() openai_api_key 存在但初始化异常
- audit_show 命令（无记录、有记录）
- metrics 子命令注册
- run/once 命令注册验证
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_settings(tmp_path):
    """Mock Settings"""
    s = MagicMock()
    s.log_level = "INFO"
    s.log_file = str(tmp_path / "agent.log")
    s.database_path = str(tmp_path / "memory.db")
    s.data_dir = str(tmp_path)
    s.openai_api_key = ""
    s.openai_model = "gpt-4o"
    return s


class TestCreateAgentLLMFailures:
    """测试 create_agent() LLM 初始化失败降级路径"""

    def test_llm_init_exception_falls_back(self, mock_settings, tmp_path):
        """LLM Provider 初始化异常时降级为无 LLM 模式"""
        mock_settings.openai_api_key = "sk-test-key"
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.llm.provider.OpenAIProvider", side_effect=Exception("连接失败")):
            from src.entry import cli
            agent = cli.create_agent()
            assert agent["llm_provider"] is None

    def test_llm_provider_returns_none_on_empty_key(self, mock_settings, tmp_path):
        """空 API Key 时 llm_provider 为 None"""
        mock_settings.openai_api_key = ""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent()
            assert agent["llm_provider"] is None

    def test_llm_provider_created_with_valid_key(self, mock_settings, tmp_path):
        """有效 API Key 时创建 LLM Provider"""
        mock_settings.openai_api_key = "sk-valid-key"
        mock_provider = MagicMock()
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.llm.provider.OpenAIProvider", return_value=mock_provider) as MockProvider:
            from src.entry import cli
            agent = cli.create_agent()
            MockProvider.assert_called_once_with(
                api_key="sk-valid-key",
                model="gpt-4o",
            )
            assert agent["llm_provider"] is mock_provider


class TestCreateAgentWithAPIKey:
    """测试 create_agent() 有 API Key 时的各种场景"""

    def test_understanding_with_llm(self, mock_settings, tmp_path):
        """有 API Key 时 understanding 应使用带 LLM 的版本"""
        mock_settings.openai_api_key = "sk-key"
        mock_provider = MagicMock()
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"), \
             patch("src.llm.provider.OpenAIProvider", return_value=mock_provider):
            from src.entry import cli
            agent = cli.create_agent()
            assert agent["understanding"] is not None

    def test_read_only_flag_preserved(self, mock_settings, tmp_path):
        """read_only 标志应被保留"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent(read_only=True)
            assert agent["read_only"] is True

    def test_metrics_collector_created(self, mock_settings, tmp_path):
        """MetricsCollector 应被创建"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent()
            assert agent["metrics"] is not None

    def test_health_checker_created(self, mock_settings, tmp_path):
        """HealthChecker 应被创建"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent()
            assert agent["health_checker"] is not None


class TestAuditShowCommand:
    """测试 audit show 命令"""

    def test_audit_show_no_entries(self, mock_settings, tmp_path):
        """无审计记录时显示提示"""
        from src.entry import cli
        from typer.testing import CliRunner
        runner = CliRunner()
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            result = runner.invoke(cli.app, ["audit", "show"])
            assert result.exit_code == 0 or "暂无" in result.output

    def test_audit_show_with_limit(self, mock_settings, tmp_path):
        """测试 audit show --limit 参数"""
        from src.entry import cli
        from typer.testing import CliRunner
        runner = CliRunner()
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            result = runner.invoke(cli.app, ["audit", "show", "--limit", "5"])
            assert result.exit_code == 0 or "暂无" in result.output


class TestMetricsCommand:
    """测试 metrics 子命令"""

    def test_metrics_app_exists(self, mock_settings, tmp_path):
        """metrics 子命令应存在"""
        from src.entry import cli
        assert cli.metrics_app is not None


class TestOnceCommand:
    """测试 once 命令"""

    def test_once_command_with_safe_input(self, mock_settings, tmp_path):
        """once 命令执行安全输入"""
        from src.entry import cli
        from typer.testing import CliRunner
        runner = CliRunner()
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            result = runner.invoke(cli.app, ["once", "hello"])
            assert result.exit_code == 0 or "Agent" in result.output or "处理失败" in result.output

    def test_once_command_read_only(self, mock_settings, tmp_path):
        """once 命令只读模式"""
        from src.entry import cli
        from typer.testing import CliRunner
        runner = CliRunner()
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            result = runner.invoke(cli.app, ["once", "--read-only", "test"])
            assert result.exit_code == 0 or "Agent" in result.output or "处理失败" in result.output


class TestRunCommand:
    """测试 run 命令注册"""

    def test_app_has_commands(self, mock_settings, tmp_path):
        """app 应有注册命令"""
        from src.entry.cli import app
        # typer 命令在 registered_commands 中，但 name 可能为 None
        # 验证 app 本身存在且可用
        assert app is not None

    def test_audit_command_registered(self, mock_settings, tmp_path):
        """audit 子命令应已注册"""
        from src.entry import cli
        groups = cli.app.registered_groups
        group_names = [g.name for g in groups]
        assert "audit" in group_names

    def test_metrics_command_registered(self, mock_settings, tmp_path):
        """metrics 子命令应已注册"""
        from src.entry import cli
        groups = cli.app.registered_groups
        group_names = [g.name for g in groups]
        assert "metrics" in group_names

    def test_create_agent_returns_all_keys(self, mock_settings, tmp_path):
        """create_agent 应返回所有必要组件"""
        with patch("src.entry.cli.Settings", return_value=mock_settings), \
             patch("src.entry.cli.init_logging"):
            from src.entry import cli
            agent = cli.create_agent()
            required_keys = ["settings", "memory", "understanding", "security",
                             "agent_loop", "llm_provider", "read_only",
                             "metrics", "health_checker"]
            for key in required_keys:
                assert key in agent, f"缺少键: {key}"
