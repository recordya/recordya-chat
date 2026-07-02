"""Tests for OpenAIProvider.stream() streaming behaviour."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from src.llm.openai import OpenAIProvider


def _delta(
    content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tc(
    index: int,
    *,
    id: str | None = None,
    type: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        id=id,
        type=type,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _chunk(
    *,
    content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
    model: str | None = "gpt-4o-mini",
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        model=model,
        usage=usage,
        choices=[SimpleNamespace(delta=_delta(content=content, tool_calls=tool_calls))],
    )


def _make_provider() -> OpenAIProvider:
    return OpenAIProvider(api_key="test-key", base_url=None, name="test-openai")


def _install_fake_stream(
    provider: OpenAIProvider,
    chunks: list[SimpleNamespace],
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_create(**kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        captured["kwargs"] = kwargs

        async def gen() -> AsyncIterator[SimpleNamespace]:
            for chunk in chunks:
                yield chunk

        return gen()

    provider._client.chat.completions.create = fake_create  # type: ignore[attr-defined]
    return captured


async def _collect(provider: OpenAIProvider, **call_kwargs: Any) -> list[dict[str, Any]]:
    return [chunk async for chunk in provider.stream(**call_kwargs)]


@pytest.mark.asyncio
async def test_stream_yields_content_deltas_in_order():
    provider = _make_provider()
    _install_fake_stream(provider, [
        _chunk(content="Hello"),
        _chunk(content=", "),
        _chunk(content="world!"),
    ])

    events = await _collect(provider, messages=[], model="gpt-4o-mini")

    content_events = [e for e in events if e["type"] == "content"]
    assert [e["delta"] for e in content_events] == ["Hello", ", ", "world!"]

    final = [e for e in events if e["type"] == "final"]
    assert len(final) == 1
    assert final[0]["content"] == "Hello, world!"
    assert final[0]["tool_calls"] is None


@pytest.mark.asyncio
async def test_stream_emits_tool_call_started_once_per_tool_index():
    provider = _make_provider()
    _install_fake_stream(provider, [
        _chunk(tool_calls=[_tc(0, id="call_1", type="function", name="search")]),
        _chunk(tool_calls=[_tc(0, arguments='{"q":')]),
        _chunk(tool_calls=[_tc(0, arguments='"hi"}')]),
    ])

    events = await _collect(provider, messages=[], model="gpt-4o-mini")

    started = [e for e in events if e["type"] == "tool_call_started"]
    assert len(started) == 1

    final = next(e for e in events if e["type"] == "final")
    assert final["content"] is None
    assert final["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "search", "arguments": '{"q":"hi"}'},
        }
    ]


@pytest.mark.asyncio
async def test_stream_emits_no_content_events_when_only_tool_calls():
    provider = _make_provider()
    _install_fake_stream(provider, [
        _chunk(tool_calls=[_tc(0, id="call_1", type="function", name="t")]),
        _chunk(tool_calls=[_tc(0, arguments='{}')]),
    ])

    events = await _collect(provider, messages=[], model="gpt-4o-mini")

    assert not [e for e in events if e["type"] == "content"]


@pytest.mark.asyncio
async def test_stream_handles_parallel_tool_calls():
    provider = _make_provider()
    _install_fake_stream(provider, [
        _chunk(tool_calls=[
            _tc(0, id="call_1", type="function", name="alpha"),
            _tc(1, id="call_2", type="function", name="beta"),
        ]),
        _chunk(tool_calls=[
            _tc(0, arguments='{"a":1}'),
            _tc(1, arguments='{"b":2}'),
        ]),
    ])

    events = await _collect(provider, messages=[], model="gpt-4o-mini")

    started = [e for e in events if e["type"] == "tool_call_started"]
    assert len(started) == 2

    final = next(e for e in events if e["type"] == "final")
    assert final["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "alpha", "arguments": '{"a":1}'},
        },
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "beta", "arguments": '{"b":2}'},
        },
    ]


@pytest.mark.asyncio
async def test_stream_text_then_tool_calls_emits_signal_after_content():
    provider = _make_provider()
    _install_fake_stream(provider, [
        _chunk(content="Thinking..."),
        _chunk(tool_calls=[_tc(0, id="call_1", type="function", name="t")]),
        _chunk(tool_calls=[_tc(0, arguments='{}')]),
    ])

    events = await _collect(provider, messages=[], model="gpt-4o-mini")

    types = [e["type"] for e in events]
    assert types.index("content") < types.index("tool_call_started")
    assert types.count("tool_call_started") == 1

    final = next(e for e in events if e["type"] == "final")
    assert final["content"] == "Thinking..."
    assert final["tool_calls"] is not None


@pytest.mark.asyncio
async def test_stream_propagates_usage_and_model_in_final():
    provider = _make_provider()
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    _install_fake_stream(provider, [
        _chunk(content="ok", model="gpt-4o-mini-2024-07-18"),
        SimpleNamespace(model="gpt-4o-mini-2024-07-18", usage=usage, choices=[]),
    ])

    events = await _collect(provider, messages=[], model="gpt-4o-mini")

    final = next(e for e in events if e["type"] == "final")
    assert final["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert final["model"] == "gpt-4o-mini-2024-07-18"


@pytest.mark.asyncio
async def test_stream_sets_stream_flags_and_request_overrides():
    provider = _make_provider()
    captured = _install_fake_stream(provider, [_chunk(content="x")])

    events = await _collect(
        provider,
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o-mini",
        temperature=0.3,
        seed=99,
    )

    assert captured["kwargs"]["stream"] is True
    assert captured["kwargs"]["stream_options"] == {"include_usage": True}

    final = next(e for e in events if e["type"] == "final")
    assert final["request_overrides"] == {"temperature": 0.3, "seed": 99}


_TOOLS = [{"type": "function", "function": {"name": "search", "parameters": {}}}]


@pytest.mark.asyncio
async def test_stream_drops_reasoning_effort_for_unsupported_model_with_tools():
    provider = _make_provider()
    captured = _install_fake_stream(provider, [_chunk(content="x")])

    await _collect(
        provider,
        messages=[],
        model="gpt-5.5",
        tools=_TOOLS,
        reasoning_effort="low",
    )

    assert "reasoning_effort" not in captured["kwargs"]


@pytest.mark.asyncio
async def test_stream_keeps_reasoning_effort_for_gpt_5_2_with_tools():
    provider = _make_provider()
    captured = _install_fake_stream(provider, [_chunk(content="x")])

    await _collect(
        provider,
        messages=[],
        model="gpt-5.2",
        tools=_TOOLS,
        reasoning_effort="low",
    )

    assert captured["kwargs"]["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_stream_keeps_reasoning_effort_for_unsupported_model_without_tools():
    provider = _make_provider()
    captured = _install_fake_stream(provider, [_chunk(content="x")])

    await _collect(
        provider,
        messages=[],
        model="gpt-5.5",
        reasoning_effort="low",
    )

    assert captured["kwargs"]["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_stream_skips_empty_choices_and_none_delta():
    provider = _make_provider()
    _install_fake_stream(provider, [
        SimpleNamespace(model="m", usage=None, choices=[]),
        SimpleNamespace(model="m", usage=None,
                        choices=[SimpleNamespace(delta=None)]),
        _chunk(content="done"),
    ])

    events = await _collect(provider, messages=[], model="gpt-4o-mini")

    content_events = [e for e in events if e["type"] == "content"]
    assert [e["delta"] for e in content_events] == ["done"]
