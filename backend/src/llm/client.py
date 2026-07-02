"""Facade for LLM provider access and parameter policy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from src.core.protocols import LLMProvider
from src.core.registry import llm_providers

from .policies import ModelPolicy


class LlmFacade:
    """Facade for a shared LLM provider with model policies."""

    def __init__(self, provider: LLMProvider, policy: ModelPolicy) -> None:
        self._provider = provider
        self._policy = policy
        self.name = provider.name
        self.supports_tools = provider.supports_tools
        self.supports_streaming = provider.supports_streaming

    def _resolve_defaults(
        self,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        purpose = kwargs.pop("purpose", "agent")
        defaults = self._policy.for_purpose(model=model, purpose=purpose)
        if temperature is not None:
            defaults["temperature"] = temperature
        if max_tokens is not None:
            defaults["max_tokens"] = max_tokens
        return defaults

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        defaults = self._resolve_defaults(model, temperature, max_tokens, kwargs)

        return await self._provider.complete(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            **defaults,
            **kwargs,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        defaults = self._resolve_defaults(model, temperature, max_tokens, kwargs)

        async for chunk in self._provider.stream(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            **defaults,
            **kwargs,
        ):
            yield chunk

    async def health_check(self) -> bool:
        return await self._provider.health_check()


@lru_cache
def get_llm_facade() -> LlmFacade:
    """Return a shared LlmFacade instance."""
    provider = llm_providers.get_instance("default")
    policy = ModelPolicy()
    return LlmFacade(provider=provider, policy=policy)


def reset_llm_facade_cache() -> None:
    """Clear cached facade instance (useful for tests)."""
    get_llm_facade.cache_clear()
