"""Tests for AgentService - agentic tool loop."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from src.core.i18n import translate
from src.core.protocols import ManagedPlugin
from src.services.agent import (
    _FALLBACK_CONTENT,
    MAX_ITERATIONS,
    AgentService,
    _friendly_error_message,
    _has_renderable_results,
)

_NESTED_WIDGET_JSON = (
    '{"_widget_type":"make_choices","_widget_payload":{"title":"T",'
    '"questions":[{"id":"q1","prompt":"P?",'
    '"options":[{"id":"a","label":"A"}]}]}}'
)


class MockPlugin(ManagedPlugin):
    """Mock plugin for testing."""

    name = "test_plugin"
    display_name = "Test Plugin"
    description = "Test data source"
    version = "1.0.0"
    source_type = "sql"  # Optional metadata

    def __init__(self) -> None:
        self.execute_tool_calls: list[tuple[str, dict[str, Any]]] = []

    async def get_system_prompt(self) -> str:
        return "You are a test assistant. Answer questions about test data."

    def get_tools_definition(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "test_query",
                    "description": "Execute a test query",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_custom_sql",
                    "description": "Generate custom SQL",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql_query": {"type": "string"},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["sql_query"],
                    },
                },
            },
        ]

    def get_predefined_tools(self) -> list[dict[str, str]]:
        return [{"name": "test_query", "description": "Test query", "sql": "SELECT 1"}]

    def get_tool_sql(self, tool_name: str) -> str | None:
        if tool_name == "test_query":
            return "SELECT 1"
        return None

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.execute_tool_calls.append((tool_name, arguments))
        if tool_name == "test_query":
            return {
                "success": True,
                "result": [{"value": 1}],
                "row_count": 1,
                "error": None,
            }
        if tool_name == "generate_custom_sql":
            return {
                "success": True,
                "result": [{"count": 42}],
                "row_count": 1,
                "sql": arguments.get("sql_query"),
                "error": None,
            }
        return {"success": False, "result": None, "error": "Unknown tool"}


class MockLLMProvider:
    """Mock LLM provider for testing."""

    name = "test_llm"
    supports_tools = True
    supports_streaming = False

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        """Initialize with predefined responses.

        Args:
            responses: List of responses to return in sequence
        """
        self.responses = responses or []
        self.call_count = 0
        self.messages_history: list[list[dict[str, Any]]] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del model, tools, tool_choice, kwargs
        self.messages_history.append([message.copy() for message in messages])

        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response

        # Default: return simple content
        return {"content": "Default response", "tool_calls": None}

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def plugin() -> MockPlugin:
    """Create mock plugin."""
    return MockPlugin()


@pytest.fixture
def llm_provider() -> MockLLMProvider:
    """Create mock LLM provider."""
    return MockLLMProvider()


async def collect_events(
    generator: AsyncGenerator[dict[str, Any], None],
) -> list[dict[str, Any]]:
    """Helper to collect all events from async generator."""
    events = []
    async for event in generator:
        events.append(event)
    return events


async def get_final_result(
    generator: AsyncGenerator[dict[str, Any], None],
) -> dict[str, Any] | None:
    """Helper to run generator and get final result from 'complete' or 'error' event."""
    events = await collect_events(generator)
    for event in events:
        if event["type"] == "complete":
            return event["data"]
        if event["type"] == "error":
            return {
                "error": event["data"]["message"],
                "content": None,
                "tool_history": [],
                "iterations": 0,
            }
    return None


# ================= Core Functionality Tests =================


@pytest.mark.asyncio
async def test_simple_text_response(plugin, llm_provider):
    """Test LLM returns text directly without tool calls."""
    llm_provider.responses = [
        {"content": "The answer is 42.", "tool_calls": None}
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("What is the answer?"))

    assert result["content"] == "The answer is 42."
    assert result["tool_history"] == []
    assert result["iterations"] == 1
    assert result["source_type"] == "sql"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_single_tool_call(plugin, llm_provider):
    """Test LLM calls one tool then returns text."""
    llm_provider.responses = [
        # First call: LLM calls a tool
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        },
        # Second call: LLM returns final answer
        {
            "content": "Based on the query, the result is 1.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Run a test query"))

    assert result["content"] == "Based on the query, the result is 1."
    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0]["tool"] == "test_query"
    assert result["tool_history"][0]["result"]["success"] is True
    assert result["iterations"] == 2
    assert result["error"] is None


@pytest.mark.asyncio
async def test_multiple_tool_calls(plugin, llm_provider):
    """Test LLM calls multiple tools in sequence."""
    llm_provider.responses = [
        # First call: predefined tool
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        },
        # Second call: custom SQL
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_2",
                    "function": {
                        "name": "generate_custom_sql",
                        "arguments": json.dumps({"sql_query": "SELECT COUNT(*) FROM test"}),
                    },
                }
            ],
        },
        # Third call: final answer
        {
            "content": "I found 42 records.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("How many records?"))

    assert result["content"] == "I found 42 records."
    assert len(result["tool_history"]) == 2
    assert result["tool_history"][0]["tool"] == "test_query"
    assert result["tool_history"][1]["tool"] == "generate_custom_sql"
    assert result["iterations"] == 3


@pytest.mark.asyncio
async def test_parallel_tool_calls(plugin, llm_provider):
    """Test LLM calls multiple tools in one response."""
    llm_provider.responses = [
        # First call: multiple tools at once
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                },
                {
                    "id": "call_2",
                    "function": {
                        "name": "generate_custom_sql",
                        "arguments": json.dumps({"sql_query": "SELECT 2"}),
                    },
                },
            ],
        },
        # Second call: final answer
        {
            "content": "Results from both queries obtained.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Run two queries"))

    assert result["content"] == "Results from both queries obtained."
    assert len(result["tool_history"]) == 2
    assert result["iterations"] == 2


@pytest.mark.asyncio
async def test_max_iterations_limit(plugin):
    """Test that max iterations limit is enforced."""
    # LLM always returns tool calls, never final answer
    llm = MockLLMProvider([
        {
            "content": None,
            "tool_calls": [
                {
                    "id": f"call_{i}",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        }
        for i in range(MAX_ITERATIONS + 5)  # More than max
    ])

    service = AgentService(plugin, llm)
    result = await get_final_result(service.run("Keep querying"))

    assert result["iterations"] == MAX_ITERATIONS
    assert result["error"] == "max_iterations_reached"
    assert "limit" in result["content"].lower()


@pytest.mark.asyncio
async def test_empty_question(plugin, llm_provider):
    """Test handling of empty question."""
    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run(""))

    assert result is not None
    assert result["error"] == translate("agent.error.missing_question")
    assert result["content"] is None


@pytest.mark.asyncio
async def test_tool_execution_error(llm_provider):
    """Test handling of tool execution errors."""

    class ErrorPlugin(MockPlugin):
        async def execute_tool(
            self,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            self.execute_tool_calls.append((tool_name, arguments))
            return {"success": False, "result": None, "error": "Database connection failed"}

    error_plugin = ErrorPlugin()

    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "content": "Sorry, there was an error executing the query.",
            "tool_calls": None,
        },
    ]

    service = AgentService(error_plugin, llm_provider)
    result = await get_final_result(service.run("Run query"))

    # Service should continue and pass error to LLM
    assert result is not None
    assert result["iterations"] == 2
    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0]["result"]["success"] is False


@pytest.mark.asyncio
async def test_conversation_history(plugin, llm_provider):
    """Test that conversation history is included."""
    llm_provider.responses = [
        {"content": "Following up on our previous conversation.", "tool_calls": None}
    ]

    history = [
        {"role": "user", "content": "What is Python?"},
        {"role": "assistant", "content": "Python is a programming language."},
    ]

    service = AgentService(plugin, llm_provider)
    await get_final_result(service.run("Tell me more", conversation_history=history))

    # Check that history was included in messages
    messages = llm_provider.messages_history[0]
    assert len(messages) == 4  # system + 2 history + current question


@pytest.mark.asyncio
async def test_tool_duration_tracking(plugin, llm_provider):
    """Test that tool execution duration is tracked."""
    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "content": "Done.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Query"))

    assert "duration_ms" in result["tool_history"][0]
    assert isinstance(result["tool_history"][0]["duration_ms"], int)
    assert result["tool_history"][0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_llm_error_handling(plugin):
    """Test handling of LLM errors."""
    from src.core.exceptions import LLMError

    class ErrorLLM:
        name = "error_llm"
        supports_tools = True
        supports_streaming = False

        async def complete(self, **kwargs):
            raise LLMError("API rate limit exceeded")

        async def health_check(self):
            return True

    service = AgentService(plugin, ErrorLLM())
    result = await get_final_result(service.run("Question"))

    # Error message should be user-friendly, not the raw exception text
    assert result["error"] is not None
    assert "API rate limit" not in result["error"]
    assert result["content"] is None


@pytest.mark.asyncio
async def test_custom_model(plugin, llm_provider):
    """Test using custom model parameter."""
    llm_provider.responses = [
        {"content": "Response from custom model", "tool_calls": None}
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Question", model="openai/gpt-4"))

    assert result["content"] == "Response from custom model"


@pytest.mark.asyncio
async def test_source_type_in_response(plugin, llm_provider):
    """Test that source_type from plugin is included in response."""
    llm_provider.responses = [
        {"content": "Answer", "tool_calls": None}
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Question"))

    assert result["source_type"] == "sql"


@pytest.mark.asyncio
async def test_malformed_tool_arguments(plugin, llm_provider):
    """Test handling of malformed JSON in tool arguments."""
    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "not valid json",  # Malformed
                    },
                }
            ],
        },
        {
            "content": "Handled the error.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Query"))

    # Should continue with empty arguments
    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0]["arguments"] == {}


@pytest.mark.asyncio
async def test_managed_plugin_prepares_tool_arguments_from_question(llm_provider):
    class PreparedPlugin(MockPlugin):
        def prepare_tool_arguments(
            self,
            tool_name: str,
            arguments: dict[str, Any],
            question: str | None = None,
            conversation_history: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any]:
            return {
                **arguments,
                "requested_from_question": question,
                "history_length": len(conversation_history or []),
            }

    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "content": "Done.",
            "tool_calls": None,
        },
    ]

    plugin = PreparedPlugin()
    service = AgentService(plugin, llm_provider)
    result = await get_final_result(
        service.run(
            "Show 3 items",
            conversation_history=[{"role": "user", "content": "Earlier turn"}],
        )
    )

    assert plugin.execute_tool_calls[0][1]["requested_from_question"] == "Show 3 items"
    assert plugin.execute_tool_calls[0][1]["history_length"] == 1
    assert result["tool_history"][0]["arguments"]["requested_from_question"] == "Show 3 items"
    assert result["tool_history"][0]["arguments"]["history_length"] == 1


@pytest.mark.asyncio
async def test_final_response_includes_latest_tool_user_notice(llm_provider):
    class NotifyingPlugin(MockPlugin):
        async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            self.execute_tool_calls.append((tool_name, arguments))
            return {
                "success": True,
                "result": [{"count": 42}],
                "row_count": 1,
                "sql": arguments.get("sql_query"),
                "error": None,
                "user_notice": "I can show at most 6 results at once.",
            }

    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "generate_custom_sql",
                        "arguments": json.dumps({"sql_query": "SELECT 42"}),
                    },
                }
            ],
        },
        {"content": "Here are the best matches.", "tool_calls": None},
    ]

    service = AgentService(NotifyingPlugin(), llm_provider)
    result = await get_final_result(service.run("Show more results"))

    assert result is not None
    assert result["content"] == "I can show at most 6 results at once. Here are the best matches."


@pytest.mark.asyncio
async def test_final_response_does_not_duplicate_existing_tool_user_notice(llm_provider):
    class NotifyingPlugin(MockPlugin):
        async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            self.execute_tool_calls.append((tool_name, arguments))
            return {
                "success": True,
                "result": [{"count": 42}],
                "row_count": 1,
                "sql": arguments.get("sql_query"),
                "error": None,
                "user_notice": "I can show at most 6 results at once.",
            }

    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "generate_custom_sql",
                        "arguments": json.dumps({"sql_query": "SELECT 42"}),
                    },
                }
            ],
        },
        {
            "content": "I can show at most 6 results at once. Here are the best matches.",
            "tool_calls": None,
        },
    ]

    service = AgentService(NotifyingPlugin(), llm_provider)
    result = await get_final_result(service.run("Show more results"))

    assert result is not None
    assert result["content"] == "I can show at most 6 results at once. Here are the best matches."


# ================= Streaming Events Tests =================


@pytest.mark.asyncio
async def test_streaming_emits_status_events(plugin, llm_provider):
    """Test streaming emits status events."""
    llm_provider.responses = [
        {"content": "Simple answer.", "tool_calls": None}
    ]

    service = AgentService(plugin, llm_provider)
    events = await collect_events(service.run("Simple question"))

    # Should have: initial status, complete
    assert len(events) >= 2

    # First event is status
    assert events[0]["type"] == "status"
    assert "message" in events[0]["data"]

    # Last event is complete
    assert events[-1]["type"] == "complete"
    assert events[-1]["data"]["content"] == "Simple answer."


@pytest.mark.asyncio
async def test_streaming_emits_tool_events(plugin, llm_provider):
    """Test streaming emits status and tool events during tool execution."""
    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "content": "Final answer after tool.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    events = await collect_events(service.run("Query something"))

    # Should have: initial status, tool status, tool complete, final complete
    event_types = [e["type"] for e in events]
    assert "status" in event_types
    assert "tool" in event_types
    assert "complete" in event_types

    # Tool event should have name and duration
    tool_events = [e for e in events if e["type"] == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["data"]["name"] == "test_query"
    assert "duration_ms" in tool_events[0]["data"]

    # Complete event should have final response
    complete_event = [e for e in events if e["type"] == "complete"][0]
    assert complete_event["data"]["content"] == "Final answer after tool."


@pytest.mark.asyncio
async def test_streaming_reasoning_in_status(plugin, llm_provider):
    """Test streaming uses reasoning from tool arguments as status."""
    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "generate_custom_sql",
                        "arguments": json.dumps({
                            "sql_query": "SELECT * FROM test",
                            "reasoning": "Looking up all records",
                        }),
                    },
                }
            ],
        },
        {
            "content": "Done.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    events = await collect_events(service.run("Find all"))

    # Find status events after the initial one
    status_events = [e for e in events if e["type"] == "status"]
    status_messages = [e["data"]["message"] for e in status_events]

    # Should include the reasoning as one of the status messages
    assert "Looking up all records" in status_messages


@pytest.mark.asyncio
async def test_streaming_status_event_includes_step_details(plugin, llm_provider):
    """Status event before a tool call includes tool_id, tool_name, arguments, reasoning."""
    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_xyz",
                    "function": {
                        "name": "generate_custom_sql",
                        "arguments": json.dumps({
                            "sql_query": "SELECT 1",
                            "reasoning": "Checking record count",
                        }),
                    },
                }
            ],
        },
        {"content": "Done.", "tool_calls": None},
    ]

    service = AgentService(plugin, llm_provider)
    events = await collect_events(service.run("How many records?"))

    status_events = [e for e in events if e["type"] == "status"]
    tool_status = next(
        e for e in status_events if e["data"].get("tool_id") == "call_xyz"
    )
    data = tool_status["data"]
    assert data["tool_name"] == "generate_custom_sql"
    assert data["reasoning"] == "Checking record count"
    assert data["step"] == 1
    assert data["arguments"] == {"sql_query": "SELECT 1"}

    tool_events = [e for e in events if e["type"] == "tool"]
    assert tool_events[0]["data"]["tool_id"] == "call_xyz"
    assert "success" in tool_events[0]["data"]
    assert "result" in tool_events[0]["data"]
    assert isinstance(tool_events[0]["data"]["result"], dict)


@pytest.mark.asyncio
async def test_streaming_error_event(plugin, llm_provider):
    """Test streaming emits error event on empty question."""
    service = AgentService(plugin, llm_provider)
    events = await collect_events(service.run(""))

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "message" in events[0]["data"]


@pytest.mark.asyncio
async def test_streaming_tool_history_in_complete(plugin, llm_provider):
    """Test streaming complete event includes full tool history."""
    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                },
                {
                    "id": "call_2",
                    "function": {
                        "name": "generate_custom_sql",
                        "arguments": json.dumps({"sql_query": "SELECT 2"}),
                    },
                },
            ],
        },
        {
            "content": "Done with both.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    events = await collect_events(service.run("Run both"))

    complete_event = [e for e in events if e["type"] == "complete"][0]
    assert len(complete_event["data"]["tool_history"]) == 2
    assert complete_event["data"]["iterations"] == 2


# ================= AgentService Helper Tests =================


class TestRenderableResults:
    def test_returns_true_for_latest_successful_non_empty_rows(self):
        tool_history = [
            {"result": {"success": True, "result": [{"value": 1}], "error": None}},
        ]

        assert _has_renderable_results(tool_history) is True

    def test_returns_false_for_empty_latest_successful_rows_without_widget(self):
        tool_history = [
            {"result": {"success": False, "result": [{"ignored": True}], "error": "boom"}},
            {"result": {"success": True, "result": [], "error": None}},
        ]

        assert _has_renderable_results(tool_history) is False


# ================= Leaked Tool Output Integration Tests =================


@pytest.mark.asyncio
async def test_leaked_tool_call_triggers_retry(plugin, llm_provider):
    """Layer 1: When LLM leaks a tool call in content, it should retry."""
    llm_provider.responses = [
        # First response: leaked tool call in content
        {
            "content": 'functions.test_query({"sql": "SELECT 1"})',
            "tool_calls": None,
        },
        # Second response after retry: proper text
        {
            "content": "The query result is 1.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Show the result"))

    assert result is not None
    assert result["content"] == "The query result is 1."
    # Should have taken 2 iterations (original + retry)
    assert result["iterations"] == 2
    # Verify correction message was appended
    assert llm_provider.call_count == 2
    last_messages = llm_provider.messages_history[1]
    correction_msg = last_messages[-1]
    assert correction_msg["role"] == "user"
    assert "tool_calls" in correction_msg["content"]


@pytest.mark.asyncio
async def test_leaked_widget_json_triggers_retry(plugin, llm_provider):
    """Layer 1: When LLM leaks widget JSON in content, it should retry."""
    llm_provider.responses = [
        {
            "content": (
                'Here are the suggestions:\n\n'
                '{"_widget_type":"voice_actor_cards","_widget_payload":{"rows":[]}}'
            ),
            "tool_calls": None,
        },
        {
            "content": "Here are the voice actor suggestions: John Smith, Anna Nowak.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Show voice actors"))

    assert result is not None
    assert result["content"] == "Here are the voice actor suggestions: John Smith, Anna Nowak."
    assert result["iterations"] == 2


@pytest.mark.asyncio
async def test_leaked_tool_call_sanitized_after_failed_retry(plugin, llm_provider):
    """Layer 2: If retry still leaks, content is sanitized."""
    llm_provider.responses = [
        # First: leaked
        {
            "content": (
                'Choose:\n\nfunctions.test_query('
                '{"filters":[{"field":"voice","values":["a","b"]}]})'
            ),
            "tool_calls": None,
        },
        # Retry: still leaked
        {
            "content": (
                'Choose an option:\n\nfunctions.test_query('
                '{"filters":[{"field":"voice","values":["a","b"]}]})'
            ),
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Show the result"))

    # Content should be sanitized — only human text remains
    assert result is not None
    assert "functions" not in result["content"]
    assert "Choose an option" in result["content"]


@pytest.mark.asyncio
async def test_leaked_widget_json_sanitized_after_failed_retry(plugin, llm_provider):
    """Layer 2: If retry still leaks widget JSON, content is sanitized."""
    llm_provider.responses = [
        {
            "content": _NESTED_WIDGET_JSON,
            "tool_calls": None,
        },
        # Retry: still only JSON
        {
            "content": _NESTED_WIDGET_JSON,
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Show it"))

    assert result is not None
    assert result["content"] == _FALLBACK_CONTENT
    assert "_widget_type" not in result["content"]


@pytest.mark.asyncio
async def test_leaked_widget_json_with_widget_results_omits_fallback(llm_provider):
    """Sanitized empty content should not show fallback when widget results exist."""

    class WidgetResultPlugin(MockPlugin):
        async def execute_tool(
            self,
            tool_name: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            self.execute_tool_calls.append((tool_name, arguments))
            return {
                "success": True,
                "result": [
                    {
                        "_widget_type": "make_choices",
                        "_widget_payload": {"title": "Pick", "questions": []},
                    }
                ],
                "row_count": 1,
                "error": None,
            }

    widget_plugin = WidgetResultPlugin()
    llm_provider.responses = [
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "test_query",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {
            "content": _NESTED_WIDGET_JSON,
            "tool_calls": None,
        },
        {
            "content": _NESTED_WIDGET_JSON,
            "tool_calls": None,
        },
    ]

    service = AgentService(widget_plugin, llm_provider)
    result = await get_final_result(service.run("Show it"))

    assert result is not None
    assert result["content"] == ""
    assert len(result["tool_history"]) == 1
    assert result["tool_history"][0]["result"]["result"][0]["_widget_type"] == "make_choices"


@pytest.mark.asyncio
async def test_no_retry_for_clean_content(plugin, llm_provider):
    """Clean content should not trigger retry or sanitization."""
    llm_provider.responses = [
        {
            "content": "Here is the voice actor list: John, Anna, Peter.",
            "tool_calls": None,
        },
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Show voice actors"))

    assert result is not None
    assert result["content"] == "Here is the voice actor list: John, Anna, Peter."
    assert result["iterations"] == 1
    assert llm_provider.call_count == 1


@pytest.mark.asyncio
async def test_retry_limited_to_max_retries(plugin, llm_provider):
    """Retry should not exceed MAX_LEAKED_TOOL_RETRIES."""
    # Provide many leaked responses — only 1 retry should happen
    llm_provider.responses = [
        {"content": 'functions.test_query({"x": "y"})', "tool_calls": None},
        {"content": 'functions.test_query({"x": "y"})', "tool_calls": None},
        {"content": 'functions.test_query({"x": "y"})', "tool_calls": None},
    ]

    service = AgentService(plugin, llm_provider)
    result = await get_final_result(service.run("Test"))

    # 1 original + 1 retry = 2 LLM calls
    assert llm_provider.call_count == 2
    assert result["iterations"] == 2



# ---------------------------------------------------------------------------
# _friendly_error_message tests
# ---------------------------------------------------------------------------


class TestFriendlyErrorMessage:
    def test_json_body_parse_error(self):
        raw = (
            "OpenAI API error: Error code: 400 - {'error': {'message': "
            "\"We could not parse the JSON body of your request.\"}}"
        )
        result = _friendly_error_message(raw)
        assert "JSON" not in result
        assert result == translate("agent.error.json_body")

    def test_context_length_exceeded(self):
        raw = "OpenAI API error: context_length_exceeded"
        result = _friendly_error_message(raw)
        assert result == translate("agent.error.context_length")

    def test_rate_limit(self):
        raw = "OpenAI API error: rate_limit_exceeded"
        result = _friendly_error_message(raw)
        assert result == translate("agent.error.rate_limit")

    def test_server_error(self):
        raw = "OpenAI API error: server_error"
        result = _friendly_error_message(raw)
        assert result == translate("agent.error.server_error")

    def test_timeout(self):
        raw = "OpenAI API error: Request timeout"
        result = _friendly_error_message(raw)
        assert result == translate("agent.error.timeout")

    def test_unknown_error_returns_generic(self):
        raw = "Some completely unexpected error XYZ123"
        result = _friendly_error_message(raw)
        assert result == translate("agent.error.generic")

    def test_case_insensitive_matching(self):
        raw = "COULD NOT PARSE THE JSON BODY"
        result = _friendly_error_message(raw)
        assert result == translate("agent.error.json_body")



# ================= Streaming (_stream_llm / run) Tests =================


class StreamingMockLLMProvider:
    """Mock LLM provider that yields streaming chunks from a scripted list.

    Each entry in ``responses`` is a list of chunk dicts (same shape as
    :meth:`BaseLLMProvider.stream` yields). Successive ``stream()`` calls
    consume entries in order.
    """

    name = "test_streaming_llm"
    supports_tools = True
    supports_streaming = True

    def __init__(self, responses: list[list[dict[str, Any]]] | None = None) -> None:
        self.responses = responses or []
        self.call_count = 0

    async def complete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {"content": "fallback", "tool_calls": None}

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        del messages, model, tools, tool_choice, kwargs
        if self.call_count >= len(self.responses):
            yield {"type": "final", "content": "done", "tool_calls": None}
            return
        chunks = self.responses[self.call_count]
        self.call_count += 1
        for chunk in chunks:
            yield chunk

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def streaming_llm_provider() -> StreamingMockLLMProvider:
    return StreamingMockLLMProvider()


@pytest.mark.asyncio
async def test_streaming_text_emits_token_events_in_order(plugin, streaming_llm_provider):
    """Text deltas from the provider are forwarded as ``token`` SSE events."""
    streaming_llm_provider.responses = [
        [
            {"type": "content", "delta": "Hello"},
            {"type": "content", "delta": ", "},
            {"type": "content", "delta": "world!"},
            {"type": "final", "content": "Hello, world!", "tool_calls": None},
        ],
    ]

    service = AgentService(plugin, streaming_llm_provider)
    events = await collect_events(service.run("Hi"))

    token_events = [e for e in events if e["type"] == "token"]
    assert [e["data"]["delta"] for e in token_events] == ["Hello", ", ", "world!"]

    complete_event = next(e for e in events if e["type"] == "complete")
    assert complete_event["data"]["content"] == "Hello, world!"


@pytest.mark.asyncio
async def test_streaming_suppresses_content_after_tool_call_started(
    plugin, streaming_llm_provider,
):
    """Variant B: once ``tool_call_started`` arrives, further content deltas are dropped."""
    streaming_llm_provider.responses = [
        [
            {"type": "content", "delta": "I'll look that up"},
            {"type": "tool_call_started"},
            {"type": "content", "delta": '{"sql":"SELECT 1"}'},
            {
                "type": "final",
                "content": 'I\'ll look that up{"sql":"SELECT 1"}',
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "test_query", "arguments": "{}"},
                    }
                ],
            },
        ],
        [
            {"type": "content", "delta": "Result: 1"},
            {"type": "final", "content": "Result: 1", "tool_calls": None},
        ],
    ]

    service = AgentService(plugin, streaming_llm_provider)
    events = await collect_events(service.run("Run query"))

    token_events = [e for e in events if e["type"] == "token"]
    token_deltas = [e["data"]["delta"] for e in token_events]

    assert "I'll look that up" in token_deltas
    assert "Result: 1" in token_deltas
    assert all('{"sql"' not in d for d in token_deltas)


@pytest.mark.asyncio
async def test_streaming_skips_empty_content_deltas(plugin, streaming_llm_provider):
    """Empty / falsy ``delta`` payloads must not produce ``token`` events."""
    streaming_llm_provider.responses = [
        [
            {"type": "content", "delta": ""},
            {"type": "content", "delta": None},
            {"type": "content", "delta": "real"},
            {"type": "final", "content": "real", "tool_calls": None},
        ],
    ]

    service = AgentService(plugin, streaming_llm_provider)
    events = await collect_events(service.run("Q"))

    token_events = [e for e in events if e["type"] == "token"]
    assert [e["data"]["delta"] for e in token_events] == ["real"]



@pytest.mark.asyncio
async def test_streaming_tool_only_iteration_emits_no_token_events(
    plugin, streaming_llm_provider,
):
    """Pure tool-call iterations stream zero ``token`` events to the UI."""
    streaming_llm_provider.responses = [
        [
            {"type": "tool_call_started"},
            {
                "type": "final",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "test_query", "arguments": "{}"},
                    }
                ],
            },
        ],
        [
            {"type": "content", "delta": "Result: 1"},
            {"type": "final", "content": "Result: 1", "tool_calls": None},
        ],
    ]

    service = AgentService(plugin, streaming_llm_provider)
    events = await collect_events(service.run("Run query"))

    tool_events = [e for e in events if e["type"] == "tool"]
    assert len(tool_events) == 1

    # Only the second iteration (commentary) streams tokens.
    token_events = [e for e in events if e["type"] == "token"]
    assert [e["data"]["delta"] for e in token_events] == ["Result: 1"]


@pytest.mark.asyncio
async def test_streaming_final_with_tool_calls_skips_token_events(
    plugin, streaming_llm_provider,
):
    """Providers that only emit a single ``final`` chunk with tool_calls do not leak tokens.

    Verifies the safety branch in ``_stream_llm`` that flips ``seen_tool_calls``
    based on the ``final`` payload even when no explicit ``tool_call_started``
    chunk was seen.
    """
    streaming_llm_provider.responses = [
        [
            {
                "type": "final",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "test_query", "arguments": "{}"},
                    }
                ],
            },
        ],
        [
            {"type": "final", "content": "Done.", "tool_calls": None},
        ],
    ]

    service = AgentService(plugin, streaming_llm_provider)
    events = await collect_events(service.run("Q"))

    assert not [e for e in events if e["type"] == "token"]
    complete_event = next(e for e in events if e["type"] == "complete")
    assert complete_event["data"]["content"] == "Done."
    assert len(complete_event["data"]["tool_history"]) == 1


@pytest.mark.asyncio
async def test_streaming_emits_token_reset_on_leaked_tool_call(
    plugin, streaming_llm_provider,
):
    """If tokens were streamed before the leaked-tool guard kicks in, FE must be told to reset."""
    streaming_llm_provider.responses = [
        # Iteration 1: streams a fake/leaked tool call as plain text.
        [
            {"type": "content", "delta": "functions.test_query("},
            {"type": "content", "delta": '{"sql":"SELECT 1"})'},
            {
                "type": "final",
                "content": 'functions.test_query({"sql":"SELECT 1"})',
                "tool_calls": None,
            },
        ],
        # Iteration 2 (retry after correction): clean text answer.
        [
            {"type": "content", "delta": "The result is 1."},
            {"type": "final", "content": "The result is 1.", "tool_calls": None},
        ],
    ]

    service = AgentService(plugin, streaming_llm_provider)
    events = await collect_events(service.run("Show the result"))

    event_types = [e["type"] for e in events]
    # token_reset is emitted between leaked iteration and retry tokens.
    assert "token_reset" in event_types

    reset_idx = event_types.index("token_reset")
    # Tokens *before* reset are the leaked draft; tokens *after* are the retry.
    pre_reset_tokens = [
        e for i, e in enumerate(events) if e["type"] == "token" and i < reset_idx
    ]
    post_reset_tokens = [
        e for i, e in enumerate(events) if e["type"] == "token" and i > reset_idx
    ]
    assert pre_reset_tokens, "leaked draft tokens should have been streamed"
    assert [e["data"]["delta"] for e in post_reset_tokens] == ["The result is 1."]

    complete_event = next(e for e in events if e["type"] == "complete")
    assert complete_event["data"]["content"] == "The result is 1."



class CancellableStreamingLLMProvider:
    """Streaming provider that suspends mid-stream until released, tracking cleanup.

    Used to verify that when the SSE consumer disconnects (i.e. stops
    iterating ``service.run()`` and calls ``aclose()`` on the generator),
    the cancellation propagates all the way down into the LLM stream so
    no further tokens are generated upstream.
    """

    name = "cancellable_streaming_llm"
    supports_tools = True
    supports_streaming = True

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.cleanup_ran = False
        self.chunks_after_first = 0

    async def complete(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {"content": "fallback", "tool_calls": None}

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        del messages, model, tools, tool_choice, kwargs
        try:
            yield {"type": "content", "delta": "first"}
            await self.release.wait()
            self.chunks_after_first += 1
            yield {"type": "content", "delta": "second"}
            yield {"type": "final", "content": "firstsecond", "tool_calls": None}
        finally:
            self.cleanup_ran = True

    async def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_streaming_task_cancellation_propagates_to_llm_stream() -> None:
    """When the SSE-driving task is cancelled, the LLM stream must be cancelled too.

    Mirrors what happens when the frontend aborts the ``fetch``: sse-starlette
    cancels the task that drives ``service.run()``. ``CancelledError`` propagates
    through every ``await`` down into the provider's ``stream()`` coroutine,
    closing the upstream LLM connection. No further chunks must be produced
    and no ``complete``/``error`` SSE event must be emitted.
    """
    plugin_instance = MockPlugin()
    provider = CancellableStreamingLLMProvider()
    service = AgentService(plugin_instance, provider)

    seen_types: list[str] = []
    first_token_event = asyncio.Event()

    async def consume() -> None:
        async for event in service.run("Hi"):
            seen_types.append(event["type"])
            if event["type"] == "token":
                first_token_event.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_token_event.wait(), timeout=1.0)

    assert "token" in seen_types
    assert provider.cleanup_ran is False

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.cleanup_ran is True
    assert provider.chunks_after_first == 0
    assert "complete" not in seen_types
    assert "error" not in seen_types


class _StubLangfuseRun:
    """In-memory stand-in for ``_LangfuseRun`` that records finish() calls."""

    def __init__(self) -> None:
        self.trace_id: str | None = "stub-trace"
        self._langfuse = None
        self.finish_calls: list[dict[str, Any]] = []

    @property
    def finished(self) -> bool:
        return bool(self.finish_calls)

    def finish(
        self,
        output: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        if self.finished:
            return
        self.finish_calls.append(
            {"output": output, "level": level, "status_message": status_message}
        )


@pytest.mark.asyncio
async def test_streaming_task_cancellation_finalizes_langfuse_trace() -> None:
    """On cancellation the Langfuse trace must be finalized (level=WARNING, cancelled)."""
    plugin_instance = MockPlugin()
    provider = CancellableStreamingLLMProvider()
    service = AgentService(plugin_instance, provider)

    stub_run = _StubLangfuseRun()
    service._start_langfuse_run = lambda *args, **kwargs: stub_run

    first_token_event = asyncio.Event()

    async def consume() -> None:
        async for event in service.run("Hi"):
            if event["type"] == "token":
                first_token_event.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_token_event.wait(), timeout=1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(stub_run.finish_calls) == 1
    assert stub_run.finish_calls[0]["level"] == "WARNING"
    assert stub_run.finish_calls[0]["status_message"] == "cancelled"


@pytest.mark.asyncio
async def test_streaming_complete_does_not_overwrite_trace_with_cancelled() -> None:
    """Normal completion finalizes the trace once; the finally branch must not re-finish it."""
    plugin_instance = MockPlugin()
    provider = StreamingMockLLMProvider(
        responses=[
            [
                {"type": "content", "delta": "ok"},
                {"type": "final", "content": "ok", "tool_calls": None},
            ],
        ],
    )
    service = AgentService(plugin_instance, provider)

    stub_run = _StubLangfuseRun()
    service._start_langfuse_run = lambda *args, **kwargs: stub_run

    await collect_events(service.run("Hi"))

    assert len(stub_run.finish_calls) == 1
    assert stub_run.finish_calls[0]["level"] is None
    assert stub_run.finish_calls[0]["status_message"] is None


@pytest.mark.asyncio
async def test_streaming_task_cancellation_preserves_partial_tokens() -> None:
    """Tokens emitted before cancellation remain observable to the consumer.

    The frontend keeps the partial assistant text as the saved reply
    (ChatGPT-style stop button). This test asserts the backend at least
    delivers those token events to the consumer before cancellation kicks in.
    """
    plugin_instance = MockPlugin()
    provider = CancellableStreamingLLMProvider()
    service = AgentService(plugin_instance, provider)

    collected_tokens: list[str] = []
    first_token_event = asyncio.Event()

    async def consume() -> None:
        async for event in service.run("Hi"):
            if event["type"] == "token":
                collected_tokens.append(event["data"]["delta"])
                first_token_event.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first_token_event.wait(), timeout=1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert collected_tokens == ["first"]
