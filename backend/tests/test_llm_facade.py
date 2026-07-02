import pytest
from unittest.mock import AsyncMock

from src.llm.client import LlmFacade
from src.llm.policies import ModelPolicy


class DummyProvider:
    def __init__(self) -> None:
        self.name = "dummy"
        self.supports_tools = True
        self.supports_streaming = True
        self.complete = AsyncMock(return_value={"content": "ok"})

    async def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_llm_facade_applies_agent_policy_defaults():
    """Test that facade applies policy defaults for standard models."""
    provider = DummyProvider()
    facade = LlmFacade(provider=provider, policy=ModelPolicy())

    await facade.complete(messages=[], model="openai/gpt-4o", purpose="agent")

    provider.complete.assert_awaited_once()
    _, kwargs = provider.complete.call_args
    assert kwargs["temperature"] == 0
    assert kwargs["seed"] == 42
    assert kwargs["max_tokens"] == 8000
    # reasoning_effort only for reasoning models, not gpt-4o
    assert "reasoning_effort" not in kwargs


@pytest.mark.asyncio
async def test_llm_facade_applies_reasoning_effort_for_o1():
    """Test that facade adds reasoning_effort for o-series models."""
    provider = DummyProvider()
    facade = LlmFacade(provider=provider, policy=ModelPolicy())

    await facade.complete(messages=[], model="openai/o1", purpose="agent")

    _, kwargs = provider.complete.call_args
    assert kwargs["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_llm_facade_allows_overrides():
    provider = DummyProvider()
    facade = LlmFacade(provider=provider, policy=ModelPolicy())

    await facade.complete(
        messages=[],
        model="openai/gpt-4o",
        purpose="agent",
        temperature=0.5,
        max_tokens=123,
    )

    _, kwargs = provider.complete.call_args
    assert kwargs["temperature"] == 0.5
    assert kwargs["max_tokens"] == 123
