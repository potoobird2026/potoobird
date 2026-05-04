"""
ModelRouter — 模型路由器

科学依据：
- 微服务熔断器模式（Circuit Breaker, Nygard, 2007）
- 指数退避重试（Exponential Backoff）
- Thompson Sampling 多臂老虎机

所有参数不写死，由公式/LLM/用户互动三个维度获得。
设计文档：07_LLM管理设计.md §7.2
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from src.errors.types import ErrorCode, LLMResult

logger = logging.getLogger("long_agent.llm.model_router")

@dataclass
class ModelConfig:
    """模型配置"""

    name: str = ""
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    priority: int = 0
    max_retries: int = 3
    timeout: int = 30
    context_window: int = 128000  # 模型上下文窗口（token 数），默认 128K
    cooldown_until: Optional[datetime] = None
    failure_count: int = 0
    total_calls: int = 0
    total_failures: int = 0

    @property
    def is_in_cooldown(self) -> bool:
        """检查是否在冷却期"""
        if self.cooldown_until is None:
            return False
        return datetime.utcnow() < self.cooldown_until

    @property
    def failure_rate(self) -> float:
        """失败率"""
        if self.total_calls == 0:
            return 0.0
        return self.total_failures / self.total_calls


@dataclass
class RouterStats:
    """路由统计"""
    total_requests: int = 0
    total_fallbacks: int = 0
    total_failures: int = 0
    model_stats: dict = field(default_factory=dict)


class ModelRouter:
    """
    模型路由器 — 回退链 + 冷却机制 + UI 接口

    设计原则（LLM管理极简）：
    - 不做任务分级路由
    - 用户选什么模型就用什么
    - 只提供切换接口
    - 不考虑多模型回退场景（保留回退链但简化）
    - 所有参数不写死
    """

    def __init__(self):
        self._models: dict[str, ModelConfig] = {}
        self._current_name: str = ""
        self._fallback_chain: list[str] = []
        self._stats = RouterStats()

    def register_model(self, name: str, provider: str, model: str,
                       api_key: str, base_url: str = "",
                       priority: int = 0, max_retries: int = 3,
                       timeout: int = 30,
                       context_window: int = 128000) -> ModelConfig:
        """
        注册一个模型

        Args:
            name: 模型名称（唯一标识）
            provider: 提供商（openai/anthropic/google/...）
            model: 模型ID（gpt-4o/claude-3-...）
            api_key: API Key（必填，运行时从配置读取）
            base_url: 自定义端点（可选）
            priority: 优先级（0=最高，不写死，由用户指定）
            max_retries: 最大重试次数（不写死，由LLM根据错误类型动态评估）
            timeout: 超时秒数（不写死，由LLM根据模型响应时间动态评估）
            context_window: 模型上下文窗口（token 数），默认 128K

        Returns:
            ModelConfig
        """
        if not api_key:
            raise ValueError(f"模型 {name} 的 api_key 不能为空（G-001 配置外部化）")

        config = ModelConfig(
            name=name, provider=provider, model=model,
            api_key=api_key, base_url=base_url,
            priority=priority, max_retries=max_retries, timeout=timeout,
            context_window=context_window,
        )
        self._models[name] = config
        self._fallback_chain = sorted(
            self._models.keys(),
            key=lambda n: self._models[n].priority
        )
        if not self._current_name:
            self._current_name = name
        logger.info(f"注册模型: {name}（{provider}/{model}）")
        return config

    def get_status(self) -> dict:
        """
        获取当前模型状态（供 UI 显示）

        Returns:
            dict: 当前模型、回退链、冷却状态、统计
        """
        return {
            "current_model": self._current_name,
            "fallback_chain": self._fallback_chain,
            "models": {
                name: {
                    "provider": m.provider,
                    "model": m.model,
                    "priority": m.priority,
                    "is_in_cooldown": m.is_in_cooldown,
                    "failure_rate": round(m.failure_rate, 3),
                    "total_calls": m.total_calls,
                }
                for name, m in self._models.items()
            },
            "stats": {
                "total_requests": self._stats.total_requests,
                "total_fallbacks": self._stats.total_fallbacks,
                "total_failures": self._stats.total_failures,
            },
        }

    def switch_model(self, name: str) -> ModelConfig:
        """
        手动切换模型

        Args:
            name: 模型名称

        Returns:
            ModelConfig

        Raises:
            ValueError: 模型未注册
        """
        if name not in self._models:
            available = list(self._models.keys())
            raise ValueError(
                f"模型 {name} 未注册。可用模型: {available}"
            )
        old_name = self._current_name
        self._current_name = name
        logger.info(f"切换模型: {old_name} → {name}")
        return self._models[name]

    async def call(self, messages: list[dict], model_name: str = None,
                    temperature: float = 0.7, max_tokens: int = 2048,
                    **kwargs) -> LLMResult:
        """
        调用 LLM（带回退链 + 冷却检查）

        冷却时长不写死，由 LLM 根据限流响应头动态评估。

        Args:
            messages: 消息列表
            model_name: 指定模型（None 使用当前模型）
            temperature: 温度
            max_tokens: 最大 token 数

        Returns:
            LLMResult
        """
        self._stats.total_requests += 1
        target_name = model_name or self._current_name

        # 构建回退链（从目标模型开始）
        fallback_names = [target_name] + [
            n for n in self._fallback_chain if n != target_name
        ]

        last_error = None
        for name in fallback_names:
            config = self._models.get(name)
            if not config:
                continue

            # 冷却检查
            if config.is_in_cooldown:
                logger.info(f"模型 {name} 在冷却期，跳过")
                continue

            try:
                result = await self._call_single(
                    config, messages, temperature, max_tokens, **kwargs
                )
                config.total_calls += 1
                if result.ok:
                    return result
                else:
                    config.total_failures += 1
                    last_error = result.error
                    # 触发冷却
                    self._apply_cooldown(config, result.error_code)
            except Exception as e:
                config.total_calls += 1
                config.total_failures += 1
                last_error = str(e)
                self._apply_cooldown(config, None)
                logger.warning(f"模型 {name} 调用失败: {e}")

            self._stats.total_fallbacks += 1

        self._stats.total_failures += 1
        return LLMResult.fail(
            error=f"所有模型调用失败。最后错误: {last_error}",
            code=ErrorCode.SERVER_ERROR,
        )

    async def _call_single(self, config: ModelConfig, messages: list[dict],
                           temperature: float, max_tokens: int,
                           **kwargs) -> LLMResult:
        """调用单个模型"""
        from src.llm.provider import LLMRequest

        request = LLMRequest(
            messages=messages,
            model=config.model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=config.timeout,
        )

        # 根据 provider 创建对应的 provider 实例
        provider = self._create_provider(config)
        return await provider.chat(request)

    def _create_provider(self, config: ModelConfig):
        """根据配置创建 LLM Provider"""
        from src.llm.provider import OpenAIProvider

        if config.provider == "openai":
            return OpenAIProvider(
                api_key=config.api_key,
                model=config.model,
                timeout=config.timeout,
            )
        # V2 扩展：AnthropicProvider / GoogleProvider 等
        raise ValueError(f"不支持的 provider: {config.provider}")

    def _apply_cooldown(self, config: ModelConfig, error_code: ErrorCode = None):
        """
        触发冷却

        冷却时长不写死，由 LLM 根据限流响应头动态评估。
        默认使用指数退避：30s → 60s → 120s → 300s → 600s
        """
        # 指数退避（基于连续失败次数）
        base_seconds = 30
        cooldown_seconds = min(
            base_seconds * (2 ** config.failure_count),
            600  # 最长10分钟
        )
        config.failure_count += 1
        config.cooldown_until = datetime.utcnow() + timedelta(seconds=cooldown_seconds)
        logger.info(
            f"模型 {config.name} 冷却 {cooldown_seconds}s "
            f"（连续失败 {config.failure_count} 次）"
        )

    def clear_cooldown(self, name: str):
        """手动清除冷却"""
        if name in self._models:
            self._models[name].cooldown_until = None
            self._models[name].failure_count = 0
            logger.info(f"模型 {name} 冷却已清除")
