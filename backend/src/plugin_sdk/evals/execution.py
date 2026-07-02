"""Shared single-turn execution helper for plugin eval runners.

Runs one AgentService turn and collects the final content + tool_history.

Usage::

    from src.plugin_sdk.evals.execution import run_single_turn

    result = await run_single_turn(plugin, llm, "Szukam lektora", model="openai/gpt-4o")
    # result == {"content": "...", "tool_history": [...]}
"""

from __future__ import annotations

from typing import Any

from src.llm.client import LlmFacade
from src.services.agent import AgentService


async def run_single_turn(
    plugin: Any,
    llm: LlmFacade,
    question: str,
    *,
    model: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run a single AgentService turn and return content + tool_history."""
    service = AgentService(plugin, llm)
    content = ""
    tool_history: list[dict[str, Any]] = []
    async for event in service.run(
        question,
        conversation_history=conversation_history,
        model=model,
    ):
        if event["type"] == "complete":
            content = event["data"].get("content", "")
            tool_history = event["data"].get("tool_history", [])
        elif event["type"] == "error":
            content = f"[ERROR] {event['data'].get('message', '')}"
    return {"content": content, "tool_history": tool_history}

