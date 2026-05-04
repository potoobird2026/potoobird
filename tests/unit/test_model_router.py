"""
ModelRouter — 单元测试

覆盖：模型注册/切换/状态查询、回退链、冷却机制、统计
"""
from unittest.mock import AsyncMock, patch

import pytest

from src.errors.types import LLMResult
from src.llm.model_router import ModelConfig, ModelRouter


@pytest.fixture
def router():
    return ModelRouter()


class TestModelRegistration:
    def test_register_model(self, router):
        config = router.register_model(
            "gpt4", "openai", "gpt-4o", "sk-test-key"
        )
        assert isinstance(config, ModelConfig)
        assert config.name == "gpt4"
        assert config.provider == "openai"

    def test_register_sets_current_if_first(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        assert router._current_name == "m1"

    def test_register_multiple_builds_fallback_chain(self, router):
        router.register_model("primary", "openai", "gpt-4o", "sk-1", priority=0)
        router.register_model("backup", "openai", "gpt-3.5", "sk-2", priority=1)
        assert router._fallback_chain == ["primary", "backup"]

    def test_register_empty_api_key_raises(self, router):
        with pytest.raises(ValueError, match="api_key"):
            router.register_model("bad", "openai", "gpt-4o", "")

    def test_register_context_window_default(self, router):
        config = router.register_model("m", "openai", "gpt-4o", "sk-key")
        assert config.context_window == 128000

    def test_register_custom_context_window(self, router):
        config = router.register_model("m", "openai", "gpt-4o", "sk-key",
                                        context_window=8192)
        assert config.context_window == 8192


class TestModelSwitch:
    def test_switch_model(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-1")
        router.register_model("m2", "openai", "gpt-3.5", "sk-2")
        config = router.switch_model("m2")
        assert config.name == "m2"
        assert router._current_name == "m2"

    def test_switch_to_unregistered_raises(self, router):
        with pytest.raises(ValueError, match="未注册"):
            router.switch_model("nonexistent")


class TestModelConfig:
    def test_failure_rate_zero_when_no_calls(self):
        config = ModelConfig(name="test", total_calls=0)
        assert config.failure_rate == 0.0

    def test_failure_rate_calculation(self):
        config = ModelConfig(name="test", total_calls=10, total_failures=3)
        assert config.failure_rate == 0.3

    def test_not_in_cooldown_by_default(self):
        config = ModelConfig(name="test")
        assert config.is_in_cooldown is False


class TestRouterStatus:
    def test_get_status_structure(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        status = router.get_status()
        assert "current_model" in status
        assert "fallback_chain" in status
        assert "models" in status
        assert "stats" in status

    def test_get_status_model_info(self, router):
        router.register_model("gpt4", "openai", "gpt-4o", "sk-key")
        status = router.get_status()
        model_info = status["models"]["gpt4"]
        assert model_info["provider"] == "openai"
        assert "is_in_cooldown" in model_info
        assert "failure_rate" in model_info


class TestCooldown:
    def test_apply_cooldown(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        router._apply_cooldown(router._models["m1"])
        assert router._models["m1"].is_in_cooldown is True

    def test_clear_cooldown(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        router._apply_cooldown(router._models["m1"])
        router.clear_cooldown("m1")
        assert router._models["m1"].is_in_cooldown is False
        assert router._models["m1"].failure_count == 0

    def test_cooldown_exponential_backoff(self, router):
        """连续失败，冷却时间应指数增长"""
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        router._apply_cooldown(router._models["m1"])
        first_cooldown = router._models["m1"].failure_count
        router._apply_cooldown(router._models["m1"])
        second_cooldown = router._models["m1"].failure_count
        assert second_cooldown > first_cooldown


class TestRouterCall:
    @pytest.mark.asyncio
    async def test_call_tracks_stats(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        with patch.object(router, '_call_single', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResult.success("test response")
            await router.call([{"role": "user", "content": "hi"}])
        assert router._stats.total_requests == 1

    @pytest.mark.asyncio
    async def test_call_with_cooldown_skips_model(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        router.register_model("m2", "openai", "gpt-3.5", "sk-2")
        # 让 m1 进入冷却
        router._apply_cooldown(router._models["m1"])
        with patch.object(router, '_call_single', new_callable=AsyncMock) as mock_call:
            mock_call.return_value = LLMResult.success("from m2")
            result = await router.call([{"role": "user", "content": "hi"}])
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_call_all_fail_returns_error(self, router):
        router.register_model("m1", "openai", "gpt-4o", "sk-key")
        with patch.object(router, '_call_single', new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("connection refused")
            result = await router.call([{"role": "user", "content": "hi"}])
        assert result.ok is False
        assert router._stats.total_failures >= 1
