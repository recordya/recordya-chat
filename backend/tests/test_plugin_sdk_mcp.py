from __future__ import annotations

import contextvars
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from src.plugin_sdk import FastMCP, FastMCPManagedPlugin, create_fastmcp_tool_adapter

_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_test", default=None)


class Selection(BaseModel):
    search_id: str
    row_index: int = Field(ge=0)


class FakeProvider:
    def populate_mcp(self, mcp: FastMCP) -> None:
        mcp.tool(meta={"status_hint": "Rendering..."})(self.render_results)

    async def render_results(
        self,
        selections: Annotated[list[Selection], Field(min_length=1)],
        mapping: dict[str, str] = Field(description="source to target mapping"),
    ) -> dict[str, Any]:
        """Render selected rows."""
        return {
            "success": True,
            "result": [
                {
                    "ctx": _ctx.get(),
                    "selections": [item.model_dump() for item in selections],
                    "mapping": mapping,
                }
            ],
            "row_count": len(selections),
        }


class PlainMethodProvider:
    def populate_mcp(self, mcp: FastMCP) -> None:
        mcp.add_tool(self.double)

    def double(self, value: int) -> dict[str, Any]:
        """Double a value."""
        return {"success": True, "result": [{"value": value * 2}], "row_count": 1}


class BrokenProvider:
    def populate_mcp(self, mcp: FastMCP) -> None:
        mcp.add_tool(self.fail)

    def fail(self) -> dict[str, Any]:
        """Always fail."""
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_registers_tools_and_builds_openai_definitions():
    # given
    toolset = create_fastmcp_tool_adapter(FakeProvider(), "test")

    # when
    await toolset.initialize()
    tools = toolset.get_openai_tools()

    # then
    assert toolset.tool_names == {"render_results"}
    assert toolset.has_tool("render_results") is True
    assert tools[0]["function"]["name"] == "render_results"
    assert tools[0]["function"]["description"] == "Render selected rows."
    assert tools[0]["status_hint"] == "Rendering..."
    params = tools[0]["function"]["parameters"]
    assert "self" not in params["properties"]
    assert params["required"] == ["selections", "mapping"]
    assert params["properties"]["selections"]["minItems"] == 1


@pytest.mark.asyncio
async def test_executes_local_tool_and_preserves_contextvar():
    # given
    toolset = create_fastmcp_tool_adapter(FakeProvider(), "test")
    _ctx.set("request-context")

    # when
    result = await toolset.call_tool(
        "render_results",
        {
            "selections": [{"search_id": "s1", "row_index": 0}],
            "mapping": {"link": "url"},
        },
    )

    # then
    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["result"][0]["ctx"] == "request-context"
    assert result["result"][0]["mapping"] == {"link": "url"}


@pytest.mark.asyncio
async def test_plain_bound_method_schema_does_not_include_self():
    # given
    toolset = create_fastmcp_tool_adapter(PlainMethodProvider(), "test")

    # when
    await toolset.initialize()
    params = toolset.get_openai_tools()[0]["function"]["parameters"]
    result = await toolset.call_tool("double", {"value": 3})

    # then
    assert "self" not in params["properties"]
    assert params["required"] == ["value"]
    assert result["result"][0]["value"] == 6


@pytest.mark.asyncio
async def test_validation_error_returns_controlled_result():
    # given
    toolset = create_fastmcp_tool_adapter(FakeProvider(), "test")

    # when
    result = await toolset.call_tool("render_results", {"selections": [], "mapping": {}})

    # then
    assert result["success"] is False
    assert "at least 1" in result["error"]
    assert result["result"] == []


@pytest.mark.asyncio
async def test_unknown_and_failing_tools_return_controlled_errors():
    # given
    toolset = create_fastmcp_tool_adapter(BrokenProvider(), "test")

    # when
    unknown = await toolset.call_tool("missing", {})
    failing = await toolset.call_tool("fail", {})

    # then
    assert unknown["success"] is False
    assert "Unknown local MCP tool" in unknown["error"]
    assert failing["success"] is False
    assert "boom" in failing["error"]


class SampleManagedPlugin(FastMCPManagedPlugin):
    name = "sample_managed"
    display_name = "Sample Managed"
    description = "Test"

    async def get_system_prompt(self) -> str:
        return "system prompt"

    def populate_mcp(self, mcp: FastMCP) -> None:
        mcp.tool(meta={"status_hint": "Echoing..."})(self.echo)

    async def echo(self, text: str) -> dict[str, Any]:
        """Echo the given text."""
        return {"success": True, "result": [{"text": text}], "row_count": 1}


class NoSuperInitPlugin(SampleManagedPlugin):
    def __init__(self) -> None:  # noqa: super-init-not-called
        self.custom = True


@pytest.mark.asyncio
async def test_fastmcp_managed_plugin_initializes_and_builds_definitions():
    # given
    plugin = SampleManagedPlugin()

    # when
    await plugin.initialize({})
    tools = plugin.get_tools_definition()

    # then
    assert tools[0]["function"]["name"] == "echo"
    assert tools[0]["function"]["description"] == "Echo the given text."
    assert tools[0]["status_hint"] == "Echoing..."
    params = tools[0]["function"]["parameters"]
    assert "self" not in params["properties"]
    assert params["required"] == ["text"]


@pytest.mark.asyncio
async def test_fastmcp_managed_plugin_executes_tool():
    # given
    plugin = SampleManagedPlugin()
    await plugin.initialize({})

    # when
    result = await plugin.execute_tool("echo", {"text": "hello"})

    # then
    assert result["success"] is True
    assert result["result"][0]["text"] == "hello"
    assert result["row_count"] == 1


@pytest.mark.asyncio
async def test_fastmcp_managed_plugin_execute_initializes_lazily():
    # given
    plugin = SampleManagedPlugin()

    # when
    result = await plugin.execute_tool("echo", {"text": "lazy"})

    # then
    assert result["success"] is True
    assert result["result"][0]["text"] == "lazy"


@pytest.mark.asyncio
async def test_fastmcp_managed_plugin_unknown_tool_returns_controlled_error():
    # given
    plugin = SampleManagedPlugin()

    # when
    result = await plugin.execute_tool("missing", {})

    # then
    assert result["success"] is False
    assert result["result"] == []
    assert result["row_count"] == 0


def test_fastmcp_managed_plugin_requires_populate_mcp():
    # given
    class IncompletePlugin(FastMCPManagedPlugin):
        name = "incomplete"

        async def get_system_prompt(self) -> str:
            return "prompt"

    # when / then
    with pytest.raises(TypeError):
        IncompletePlugin()


@pytest.mark.asyncio
async def test_fastmcp_managed_plugin_without_super_init_still_works():
    # given
    plugin = NoSuperInitPlugin()

    # when
    await plugin.initialize({})
    tools = plugin.get_tools_definition()
    result = await plugin.execute_tool("echo", {"text": "ok"})

    # then
    assert tools[0]["function"]["name"] == "echo"
    assert result["success"] is True
