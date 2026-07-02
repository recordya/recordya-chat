"""Tests for CoreEngine - primitives for plugins."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.engine import CoreEngine
from src.core.protocols import LLMRequest, LLMResponse, ToolCall, ToolResult


class MockLLMClient:
    """Mock LLM client for testing."""
    
    def __init__(self, response: dict | None = None):
        self.response = response or {"content": "Test response", "tool_calls": None}
        self.call_count = 0
        self.last_call = None
    
    async def complete(self, **kwargs) -> dict:
        self.call_count += 1
        self.last_call = kwargs
        return self.response


class MockObservabilityProvider:
    """Mock observability provider for testing."""
    
    def __init__(self):
        self.traces = []
        self.llm_calls = []
        self.tool_calls = []
        self.errors = []
        self.flushed = False
    
    def start_trace(self, name: str, metadata: dict | None = None):
        trace = {"name": name, "metadata": metadata}
        self.traces.append(trace)
        return trace
    
    def log_llm_call(self, trace, request: dict, response: dict, duration_ms: int):
        self.llm_calls.append({
            "trace": trace,
            "request": request,
            "response": response,
            "duration_ms": duration_ms,
        })
    
    def log_tool_call(
        self, trace, tool_name: str, arguments: dict, result, success: bool, duration_ms: int
    ):
        self.tool_calls.append({
            "trace": trace,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
            "success": success,
            "duration_ms": duration_ms,
        })
    
    def log_error(self, trace, error: str):
        self.errors.append({"trace": trace, "error": error})
    
    def flush(self):
        self.flushed = True


@pytest.fixture
def llm_client():
    return MockLLMClient()


@pytest.fixture
def observability():
    return MockObservabilityProvider()


@pytest.fixture
def engine(llm_client, observability):
    return CoreEngine(
        llm_client=llm_client,
        tool_registry={},
        state_store={},
        observability=observability,
    )


# ================= LLM Primitives Tests =================


@pytest.mark.asyncio
async def test_call_llm_basic(engine, llm_client):
    """Test basic LLM call."""
    request = LLMRequest(
        messages=[{"role": "user", "content": "Hello"}],
        model="gpt-4o",
    )
    
    response = await engine.call_llm(request)
    
    assert response.content == "Test response"
    assert llm_client.call_count == 1
    assert llm_client.last_call["messages"] == [{"role": "user", "content": "Hello"}]


@pytest.mark.asyncio
async def test_call_llm_with_tools(engine, llm_client):
    """Test LLM call with tools."""
    llm_client.response = {
        "content": None,
        "tool_calls": [{"id": "call_1", "function": {"name": "test", "arguments": "{}"}}],
    }
    
    request = LLMRequest(
        messages=[{"role": "user", "content": "Use tool"}],
        model="gpt-4o",
        tools=[{"type": "function", "function": {"name": "test"}}],
    )
    
    response = await engine.call_llm(request)
    
    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1


@pytest.mark.asyncio
async def test_call_llm_logs_to_observability(engine, llm_client, observability):
    """Test that LLM calls are logged to observability."""
    # Start a session first
    await engine.start_session("session_1", "test_plugin", "Hello")
    
    request = LLMRequest(
        messages=[{"role": "user", "content": "Hello"}],
        model="gpt-4o",
    )
    
    await engine.call_llm(request)
    
    assert len(observability.llm_calls) == 1
    assert observability.llm_calls[0]["request"]["model"] == "gpt-4o"


# ================= Tool Primitives Tests =================


@pytest.mark.asyncio
async def test_execute_tool_with_handler(engine):
    """Test tool execution with explicit handler."""
    async def test_handler(args):
        return {"data": "result", "value": args.get("x", 0) * 2}
    
    call = ToolCall(id="call_1", name="test_tool", arguments={"x": 5})
    result = await engine.execute_tool(call, handler=test_handler)
    
    assert result.success is True
    assert result.data["value"] == 10


@pytest.mark.asyncio
async def test_execute_tool_unknown(engine):
    """Test tool execution with unknown tool."""
    call = ToolCall(id="call_1", name="unknown_tool", arguments={})
    result = await engine.execute_tool(call)
    
    assert result.success is False
    assert "Unknown tool" in result.error


@pytest.mark.asyncio
async def test_execute_tool_handler_error(engine):
    """Test tool execution with handler error."""
    async def error_handler(args):
        raise ValueError("Handler error")
    
    call = ToolCall(id="call_1", name="test_tool", arguments={})
    result = await engine.execute_tool(call, handler=error_handler)
    
    assert result.success is False
    assert "Handler error" in result.error


@pytest.mark.asyncio
async def test_execute_tool_logs_to_observability(engine, observability):
    """Test that tool calls are logged to observability."""
    await engine.start_session("session_1", "test_plugin", "Test")
    
    async def test_handler(args):
        return {"result": "ok"}
    
    call = ToolCall(id="call_1", name="test_tool", arguments={"key": "value"})
    await engine.execute_tool(call, handler=test_handler)
    
    assert len(observability.tool_calls) == 1
    assert observability.tool_calls[0]["tool_name"] == "test_tool"
    assert observability.tool_calls[0]["success"] is True


@pytest.mark.asyncio
async def test_execute_tools_parallel(engine):
    """Test parallel tool execution."""
    async def handler_a(args):
        return {"tool": "A"}
    
    async def handler_b(args):
        return {"tool": "B"}
    
    calls = [
        ToolCall(id="call_1", name="tool_a", arguments={}),
        ToolCall(id="call_2", name="tool_b", arguments={}),
    ]
    handlers = {"tool_a": handler_a, "tool_b": handler_b}
    
    results = await engine.execute_tools_parallel(calls, handlers)
    
    assert len(results) == 2
    assert results[0].success is True
    assert results[0].data["tool"] == "A"
    assert results[1].data["tool"] == "B"


# ================= State Primitives Tests =================


@pytest.mark.asyncio
async def test_state_get_set(engine):
    """Test state get and set."""
    await engine.set_state("session_1", "key", "value")
    result = await engine.get_state("session_1", "key")
    
    assert result == "value"


@pytest.mark.asyncio
async def test_state_get_missing(engine):
    """Test state get for missing key."""
    result = await engine.get_state("session_1", "nonexistent")
    
    assert result is None


@pytest.mark.asyncio
async def test_state_isolation(engine):
    """Test state isolation between sessions."""
    await engine.set_state("session_1", "key", "value_1")
    await engine.set_state("session_2", "key", "value_2")
    
    result_1 = await engine.get_state("session_1", "key")
    result_2 = await engine.get_state("session_2", "key")
    
    assert result_1 == "value_1"
    assert result_2 == "value_2"


# ================= Session Management Tests =================


@pytest.mark.asyncio
async def test_session_lifecycle(engine, observability):
    """Test session start and end."""
    await engine.start_session("session_1", "test_plugin", "Hello")
    
    assert len(observability.traces) == 1
    assert observability.traces[0]["name"] == "test_plugin_session"
    assert engine._current_trace is not None
    
    await engine.end_session()
    
    assert observability.flushed is True
    assert engine._current_trace is None


# ================= Event Emission Tests =================


def test_emit_status(engine):
    """Test status event emission."""
    event = engine.emit_status("Processing...", step=1)
    
    assert event["type"] == "status"
    assert event["data"]["message"] == "Processing..."
    assert event["data"]["step"] == 1


def test_emit_tool(engine):
    """Test tool event emission."""
    event = engine.emit_tool("test_tool", duration_ms=150)
    
    assert event["type"] == "tool"
    assert event["data"]["name"] == "test_tool"
    assert event["data"]["duration_ms"] == 150



def test_emit_complete(engine):
    """Test complete event emission."""
    event = engine.emit_complete(
        content="Done!",
        tool_history=[{"tool": "test"}],
        iterations=2,
        trace_id="trace_123",
    )
    
    assert event["type"] == "complete"
    assert event["data"]["content"] == "Done!"
    assert event["data"]["tool_history"] == [{"tool": "test"}]
    assert event["data"]["iterations"] == 2
    assert event["data"]["langfuse_trace_id"] == "trace_123"


def test_emit_error(engine):
    """Test error event emission."""
    event = engine.emit_error("Something went wrong", trace_id="trace_123")
    
    assert event["type"] == "error"
    assert event["data"]["message"] == "Something went wrong"
    assert event["data"]["langfuse_trace_id"] == "trace_123"


# ================= Legacy Tool Result Handling Tests =================


@pytest.mark.asyncio
async def test_execute_tool_legacy_dict_result(engine):
    """Test tool execution with legacy dict result format."""
    async def legacy_handler(args):
        return {
            "success": True,
            "result": [{"value": 1}],
            "row_count": 1,
            "sql": "SELECT 1",
            "tool_type": "predefined",
        }
    
    call = ToolCall(id="call_1", name="legacy_tool", arguments={})
    result = await engine.execute_tool(call, handler=legacy_handler)

    assert result.success is True
    assert result.data == [{"value": 1}]
    assert result.sql == "SELECT 1"
    assert result.tool_type == "predefined"
    assert result.row_count == 1


