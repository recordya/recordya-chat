import json

import pytest

from src.core.config import settings
from src.core.protocols import ContextConfig
from src.services.agent_helpers import (
    ConversationBuilder,
    ToolExecutionService,
    _safe_json_dumps,
    _sanitize_floats,
)

# ---------------------------------------------------------------------------
# Generic test constants — no plugin-specific knowledge
# ---------------------------------------------------------------------------
_TEST_WIDGET = "test_data_widget"
_TEST_PK = "item_id"
_TEST_DISPLAY = "name"

_TEST_CTX_CFG = ContextConfig(
    data_widget_types=frozenset({_TEST_WIDGET}),
    primary_key=_TEST_PK,
    display_field=_TEST_DISPLAY,
)


def _row(pk_value: int, display_value: str) -> dict:
    """Build a generic test row."""
    return {_TEST_PK: pk_value, _TEST_DISPLAY: display_value}


def _widget(rows: list[dict]) -> dict:
    """Wrap rows in a generic test widget."""
    return {"_widget_type": _TEST_WIDGET, "_widget_payload": {"rows": rows}}


class DummyPlugin:
    def __init__(self, *, context_config: ContextConfig | None = _TEST_CTX_CFG) -> None:
        self.name = "dummy"
        self._context_config = context_config
        self.execute_tool_calls: list[tuple[str, dict]] = []

    async def get_system_prompt(self) -> str:
        """Plugin builds complete system prompt including dynamic data."""
        return "SYSTEM_PROMPT with categories: test, drama"

    async def execute_tool(self, tool_name: str, arguments: dict) -> dict:
        self.execute_tool_calls.append((tool_name, arguments))
        return {"success": True, "result": [{"value": 1}], "error": None}

    def prepare_tool_arguments(
        self,
        tool_name: str,
        arguments: dict,
        question: str | None = None,
        conversation_history: list[dict] | None = None,
    ) -> dict:
        return arguments

    def get_context_config(self) -> ContextConfig | None:
        return self._context_config


@pytest.mark.asyncio
async def test_conversation_builder_includes_history_and_question():
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Any news?",
        conversation_history=[
            {"role": "user", "content": "Show ranking"},
            {"role": "assistant", "content": "Here is the ranking"},
        ],
    )

    assert messages[0]["role"] == "system"
    assert "SYSTEM_PROMPT" in messages[0]["content"]
    assert "categories" in messages[0]["content"]
    assert messages[-1]["content"] == "Any news?"


@pytest.mark.asyncio
async def test_conversation_builder_injects_context_from_widget_wrapped_results():
    """Widget-wrapped results inject a context block into the user message."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Show others",
        conversation_history=[
            {"role": "user", "content": "Search items"},
            {
                "role": "assistant",
                "content": "Here are results",
                "queryResults": [_widget([_row(1, "Alpha"), _row(2, "Beta")])],
            },
        ],
    )

    assert len(messages) == 4
    assert messages[2]["role"] == "assistant"
    assert "[CONTEXT:" not in messages[2]["content"]
    user_msg = messages[3]
    assert user_msg["role"] == "user"
    assert user_msg["content"].startswith("[CONTEXT:")
    assert "Alpha (item_id=1)" in user_msg["content"]
    assert "Beta (item_id=2)" in user_msg["content"]
    assert "Show others" in user_msg["content"]


@pytest.mark.asyncio
async def test_conversation_builder_injects_context_from_flat_rows():
    """Flat rows (no widget wrapper) should also work."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Show others",
        conversation_history=[
            {"role": "user", "content": "Search items"},
            {
                "role": "assistant",
                "content": "Here are results",
                "queryResults": [_row(1, "Alpha"), _row(2, "Beta")],
            },
        ],
    )

    user_msg = messages[-1]
    assert user_msg["content"].startswith("[CONTEXT:")
    assert "Alpha (item_id=1)" in user_msg["content"]
    assert "Beta (item_id=2)" in user_msg["content"]


@pytest.mark.asyncio
async def test_conversation_builder_accumulates_across_turns():
    """Widget-wrapped results from multiple turns are accumulated."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="More please",
        conversation_history=[
            {"role": "user", "content": "Search items"},
            {
                "role": "assistant",
                "content": "Turn 1",
                "queryResults": [_widget([_row(1, "Alpha")])],
            },
            {"role": "user", "content": "Show others"},
            {
                "role": "assistant",
                "content": "Turn 2",
                "queryResults": [_widget([_row(3, "Gamma")])],
            },
        ],
    )

    user_msg = messages[-1]
    assert user_msg["role"] == "user"
    assert user_msg["content"].startswith("[CONTEXT:")
    assert "Alpha (item_id=1)" in user_msg["content"]
    assert "Gamma (item_id=3)" in user_msg["content"]


@pytest.mark.asyncio
async def test_conversation_builder_deduplicates_primary_keys():
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Test",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Turn 1",
                "queryResults": [_row(1, "Alpha")],
            },
            {
                "role": "assistant",
                "content": "Turn 2",
                "queryResults": [_row(1, "Alpha"), _row(2, "Beta")],
            },
        ],
    )

    user_msg = messages[-1]
    assert user_msg["role"] == "user"
    assert "Alpha (item_id=1)" in user_msg["content"]
    assert "Beta (item_id=2)" in user_msg["content"]
    assert user_msg["content"].count("Alpha") == 1


@pytest.mark.asyncio
async def test_conversation_builder_skips_non_data_widgets():
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Continue",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Response",
                "queryResults": [
                    {"_widget_type": "make_choices", "_widget_payload": {}},
                ],
            },
        ],
    )

    # No context injected — only system + assistant-history + user
    assert len(messages) == 3
    assert messages[-1]["role"] == "user"
    assert messages[-2]["role"] == "assistant"


@pytest.mark.asyncio
async def test_conversation_builder_no_summary_without_query_results():
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Test",
        conversation_history=[
            {"role": "assistant", "content": "Plain response"},
        ],
    )

    assert len(messages) == 3
    assert messages[1]["content"] == "Plain response"
    assert messages[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_conversation_builder_ignores_unknown_widget_type():
    """Unknown widget types are silently ignored (allowlist)."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Test",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Response",
                "queryResults": [
                    {
                        "_widget_type": "some_future_widget",
                        "_widget_payload": {"rows": [_row(99, "Unknown")]},
                    }
                ],
            },
        ],
    )

    assert len(messages) == 3
    assert messages[-1]["content"] == "Test"


@pytest.mark.asyncio
async def test_conversation_builder_mixed_widgets_in_one_turn():
    """Data widget is collected, interaction widget is skipped."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Show others",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Results + question",
                "queryResults": [
                    {"_widget_type": "make_choices", "_widget_payload": {"questions": []}},
                    _widget([_row(5, "Epsilon")]),
                ],
            },
        ],
    )

    user_msg = messages[-1]
    assert "Epsilon (item_id=5)" in user_msg["content"]


@pytest.mark.asyncio
async def test_conversation_builder_skips_turn_without_results():
    """Turns without queryResults don't break accumulation from other turns."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Anyone else?",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Turn 1 with results",
                "queryResults": [_widget([_row(1, "Alpha")])],
            },
            {"role": "user", "content": "Tell me more"},
            {"role": "assistant", "content": "Turn 2 without results"},
            {"role": "user", "content": "Show others"},
            {
                "role": "assistant",
                "content": "Turn 3 with results",
                "queryResults": [_widget([_row(7, "Eta")])],
            },
        ],
    )

    user_msg = messages[-1]
    assert "Alpha (item_id=1)" in user_msg["content"]
    assert "Eta (item_id=7)" in user_msg["content"]


@pytest.mark.asyncio
async def test_conversation_builder_rows_without_primary_key():
    """Rows missing the primary key don't crash and don't appear in context."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Test",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Results",
                "queryResults": [
                    _widget([
                        {_TEST_DISPLAY: "No PK"},
                        _row(3, "Has PK"),
                    ])
                ],
            },
        ],
    )

    user_msg = messages[-1]
    assert "Has PK (item_id=3)" in user_msg["content"]
    assert "No PK" not in user_msg["content"]


@pytest.mark.asyncio
async def test_conversation_builder_respects_max_summary_rows():
    """Only _MAX_SUMMARY_ROWS (10) items appear in the context."""
    plugin = DummyPlugin()
    builder = ConversationBuilder(plugin)
    rows = [_row(i, f"Item {i}") for i in range(1, 13)]
    messages = await builder.build_messages(
        question="Next",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Many results",
                "queryResults": [_widget(rows)],
            },
        ],
    )

    user_msg = messages[-1]
    assert "Item 10 (item_id=10)" in user_msg["content"]
    assert "Item 11" not in user_msg["content"]
    assert "Item 12" not in user_msg["content"]


@pytest.mark.asyncio
async def test_conversation_builder_no_context_when_plugin_returns_none():
    """Plugin with get_context_config() -> None gets no context injection."""
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="Test",
        conversation_history=[
            {
                "role": "assistant",
                "content": "Results",
                "queryResults": [_widget([_row(1, "Alpha")])],
            },
        ],
    )

    assert messages[-1]["content"] == "Test"
    assert "[CONTEXT:" not in messages[-1]["content"]


@pytest.mark.asyncio
async def test_tool_execution_service_tracks_results_and_messages():
    plugin = DummyPlugin()
    service = ToolExecutionService(plugin, langfuse=None)

    tool_calls = [
        {
            "id": "1",
            "function": {
                "name": "test_tool",
                "arguments": "{}",
            },
        }
    ]
    messages = []
    history = []
    parsed = service.parse_tool_calls(tool_calls)
    executed = await service.execute_parsed_calls(parsed, messages, history)

    assert len(executed) == 1
    assert history[0]["tool"] == "test_tool"
    assert messages[-1]["role"] == "tool"


@pytest.mark.asyncio
async def test_tool_execution_service_prepares_arguments_from_question():
    class PreparedDummyPlugin(DummyPlugin):
        def prepare_tool_arguments(
            self,
            tool_name: str,
            arguments: dict,
            question: str | None = None,
            conversation_history: list[dict] | None = None,
        ) -> dict:
            return {
                **arguments,
                "requested_from_question": question,
                "history_length": len(conversation_history or []),
            }

    plugin = PreparedDummyPlugin()
    service = ToolExecutionService(
        plugin,
        langfuse=None,
        question="Show 3 items",
        conversation_history=[{"role": "user", "content": "Earlier turn"}],
    )

    parsed = service.parse_tool_calls(
        [
            {
                "id": "1",
                "function": {"name": "test_tool", "arguments": "{}"},
            }
        ]
    )
    messages = []
    history = []
    await service.execute_parsed_calls(parsed, messages, history)

    assert history[0]["arguments"]["requested_from_question"] == "Show 3 items"
    assert history[0]["arguments"]["history_length"] == 1
    assert plugin.execute_tool_calls[0][1]["requested_from_question"] == "Show 3 items"
    assert plugin.execute_tool_calls[0][1]["history_length"] == 1



# ---------------------------------------------------------------------------
# Tool-call history replay tests
# ---------------------------------------------------------------------------


def _tool_result(
    tool_name: str = "run_sql",
    tool_call_id: str | None = "call_abc",
    arguments: dict | None = None,
    rows: list[dict] | None = None,
    success: bool = True,
) -> dict:
    return {
        "tool": tool_name,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "arguments": arguments or {"sql": "SELECT 1"},
        "result": {
            "success": success,
            "result": rows if rows is not None else [{"a": 1}],
            "error": None,
        },
    }


@pytest.mark.asyncio
async def test_conversation_builder_replays_tool_history_full():
    """Assistant message with toolResults emits assistant+tool_calls + tool msg + final content."""
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="And the next ones?",
        conversation_history=[
            {"role": "user", "content": "Show items"},
            {
                "role": "assistant",
                "content": "Here are the items.",
                "toolResults": [_tool_result(rows=[{"id": 1, "name": "Alpha"}])],
            },
        ],
    )

    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "Show items"}
    assistant_call = messages[2]
    assert assistant_call["role"] == "assistant"
    assert assistant_call["content"] == ""
    assert assistant_call["tool_calls"][0]["id"] == "call_abc"
    assert assistant_call["tool_calls"][0]["function"]["name"] == "run_sql"
    assert json.loads(assistant_call["tool_calls"][0]["function"]["arguments"]) == {
        "sql": "SELECT 1"
    }

    tool_msg = messages[3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_abc"
    payload = json.loads(tool_msg["content"])
    assert payload["result"] == [{"id": 1, "name": "Alpha"}]

    assert messages[4] == {"role": "assistant", "content": "Here are the items."}
    assert messages[-1] == {"role": "user", "content": "And the next ones?"}


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_synthesizes_id_when_missing():
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="next",
        conversation_history=[
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "ok",
                "toolResults": [_tool_result(tool_call_id=None)],
            },
        ],
    )

    assistant_call = next(m for m in messages if m.get("tool_calls"))
    synth_id = assistant_call["tool_calls"][0]["id"]
    assert synth_id.startswith("call_")
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == synth_id


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_serializes_multiple_tool_calls_sequentially():
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="more",
        conversation_history=[
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "done",
                "toolResults": [
                    _tool_result(
                        tool_name="lookup_items",
                        tool_call_id="c1",
                        arguments={"query": "items"},
                        rows=[{"x": 1}],
                    ),
                    _tool_result(
                        tool_name="render_items",
                        tool_call_id="c2",
                        arguments={
                            "selections": [{"lookup_id": "lookup-1", "row_index": 0}],
                            "mapping": {"source_link": "target_url"},
                        },
                        rows=[{"x": 2}],
                    ),
                ],
            },
        ],
    )

    assistant_calls = [m for m in messages if m.get("tool_calls")]
    assert len(assistant_calls) == 2
    assert [len(m["tool_calls"]) for m in assistant_calls] == [1, 1]
    assert [m["tool_calls"][0]["id"] for m in assistant_calls] == ["c1", "c2"]
    assert [
        m["tool_calls"][0]["function"]["name"] for m in assistant_calls
    ] == ["lookup_items", "render_items"]

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]

    c1_index = messages.index(assistant_calls[0])
    c2_index = messages.index(assistant_calls[1])
    assert messages[c1_index + 1]["tool_call_id"] == "c1"
    assert c2_index > c1_index + 1
    assert messages[c2_index + 1]["tool_call_id"] == "c2"


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_skips_legacy_context_block():
    """New tool history present → [CONTEXT:] not prepended even with ContextConfig."""
    plugin = DummyPlugin()  # has _TEST_CTX_CFG
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="ask again",
        conversation_history=[
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "answer",
                "toolResults": [_tool_result()],
                "queryResults": [_widget([_row(1, "Alpha")])],
            },
        ],
    )

    assert messages[-1] == {"role": "user", "content": "ask again"}
    assert not messages[-1]["content"].startswith("[CONTEXT:")


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_degrades_when_budget_tight(monkeypatch):
    """When the budget is too small for full mode, rows are truncated."""
    monkeypatch.setattr(settings, "CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET", 200)
    monkeypatch.setattr(settings, "CONVERSATION_DEGRADED_MAX_ROWS", 2)

    big_rows = [{"id": i, "label": f"item-{i}" * 5} for i in range(50)]
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="next",
        conversation_history=[
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "done",
                "toolResults": [_tool_result(rows=big_rows)],
            },
        ],
    )

    tool_msg = next(m for m in messages if m["role"] == "tool")
    payload = json.loads(tool_msg["content"])
    assert payload["_truncated"] is True
    assert payload["_original_row_count"] == 50
    assert len(payload["result"]) == 2


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_falls_back_to_text_when_very_tight(monkeypatch):
    """Extremely tight budget collapses old turns to text_only (no tool messages)."""
    monkeypatch.setattr(settings, "CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET", 30)
    monkeypatch.setattr(settings, "CONVERSATION_DEGRADED_MAX_ROWS", 2)

    big_rows = [{"id": i, "label": f"item-{i}" * 20} for i in range(100)]
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="next",
        conversation_history=[
            {"role": "user", "content": "old q"},
            {
                "role": "assistant",
                "content": "old answer",
                "toolResults": [_tool_result(rows=big_rows)],
            },
            {"role": "user", "content": "recent q"},
            {
                "role": "assistant",
                "content": "recent answer",
                "toolResults": [_tool_result(rows=big_rows)],
            },
        ],
    )

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert tool_msgs == []
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    contents = [m.get("content") for m in assistant_msgs]
    assert "old answer" in contents
    assert "recent answer" in contents


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_prioritizes_recent_turns(monkeypatch):
    """Limited budget keeps the newest turn full and degrades/drops detail from older ones."""
    monkeypatch.setattr(settings, "CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET", 400)
    monkeypatch.setattr(settings, "CONVERSATION_DEGRADED_MAX_ROWS", 1)

    big_rows = [{"id": i, "label": "x" * 50} for i in range(40)]
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="now",
        conversation_history=[
            {"role": "user", "content": "old"},
            {
                "role": "assistant",
                "content": "old answer",
                "toolResults": [_tool_result(tool_call_id="old", rows=big_rows)],
            },
            {"role": "user", "content": "recent"},
            {
                "role": "assistant",
                "content": "recent answer",
                "toolResults": [_tool_result(tool_call_id="recent", rows=big_rows)],
            },
        ],
    )

    tool_msgs = [m for m in messages if m["role"] == "tool"]
    recent_ids = [m["tool_call_id"] for m in tool_msgs]
    assert "recent" in recent_ids
    if "old" in recent_ids:
        old_payload = json.loads(
            next(m for m in tool_msgs if m["tool_call_id"] == "old")["content"]
        )
        recent_payload = json.loads(
            next(m for m in tool_msgs if m["tool_call_id"] == "recent")["content"]
        )
        assert len(recent_payload["result"]) >= len(old_payload["result"])


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_respects_max_turns(monkeypatch):
    """Only the last CONVERSATION_MAX_TURNS turns are replayed."""
    monkeypatch.setattr(settings, "CONVERSATION_MAX_TURNS", 2)

    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    history = []
    for i in range(5):
        history.append({"role": "user", "content": f"q{i}"})
        history.append({
            "role": "assistant",
            "content": f"a{i}",
            "toolResults": [_tool_result(tool_call_id=f"id{i}")],
        })

    messages = await builder.build_messages(question="now", conversation_history=history)

    tool_call_ids = [
        tc["id"]
        for m in messages
        if m.get("tool_calls")
        for tc in m["tool_calls"]
    ]
    assert tool_call_ids == ["id3", "id4"]


@pytest.mark.asyncio
async def test_conversation_builder_tool_replay_tolerates_orphan_user_message():
    """Trailing user message (no assistant reply yet) does not crash replay."""
    plugin = DummyPlugin(context_config=None)
    builder = ConversationBuilder(plugin)
    messages = await builder.build_messages(
        question="now",
        conversation_history=[
            {"role": "user", "content": "first"},
            {
                "role": "assistant",
                "content": "answer",
                "toolResults": [_tool_result()],
            },
            {"role": "user", "content": "dangling"},
        ],
    )

    user_contents = [m["content"] for m in messages if m["role"] == "user"]
    assert "first" in user_contents
    assert "dangling" in user_contents
    assert messages[-1] == {"role": "user", "content": "now"}


def test_conversation_builder_degrade_result_keeps_small_lists(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_DEGRADED_MAX_ROWS", 20)
    result = {"success": True, "result": [{"i": i} for i in range(5)], "error": None}
    assert ConversationBuilder._degrade_result(result) == result


def test_conversation_builder_degrade_result_truncates_long_lists(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_DEGRADED_MAX_ROWS", 3)
    rows = [{"i": i} for i in range(50)]
    out = ConversationBuilder._degrade_result(
        {"success": True, "result": rows, "error": None}
    )
    assert len(out["result"]) == 3
    assert out["_truncated"] is True
    assert out["_original_row_count"] == 50


def test_conversation_builder_degrade_result_handles_non_dict():
    assert ConversationBuilder._degrade_result("hello") == "hello"
    assert ConversationBuilder._degrade_result(None) is None
    assert ConversationBuilder._degrade_result([1, 2, 3]) == [1, 2, 3]


def test_conversation_builder_synthesize_tool_calls_preserves_arguments():
    out = ConversationBuilder._synthesize_tool_calls(
        [
            {
                "tool_call_id": "abc",
                "tool_name": "run_sql",
                "arguments": {"sql": "SELECT 1"},
            }
        ]
    )
    assert out == [
        {
            "id": "abc",
            "type": "function",
            "function": {
                "name": "run_sql",
                "arguments": '{"sql": "SELECT 1"}',
            },
        }
    ]


def test_conversation_builder_synthesize_tool_calls_falls_back_to_tool_field():
    out = ConversationBuilder._synthesize_tool_calls(
        [{"tool_call_id": "x", "tool": "legacy_name", "arguments": {}}]
    )
    assert out[0]["function"]["name"] == "legacy_name"


@pytest.mark.asyncio
async def test_tool_execution_service_records_tool_call_id_in_history():
    """Regression: tool_call_id is propagated into tool_history entries."""
    plugin = DummyPlugin()
    service = ToolExecutionService(plugin, langfuse=None)
    parsed = service.parse_tool_calls(
        [{"id": "call_xyz", "function": {"name": "test_tool", "arguments": "{}"}}]
    )
    messages: list = []
    history: list = []
    await service.execute_parsed_calls(parsed, messages, history)

    assert history[0]["tool_call_id"] == "call_xyz"


class TestSanitizeFloats:
    def test_nan_replaced_with_none(self):
        assert _sanitize_floats(float("nan")) is None

    def test_positive_infinity_replaced_with_none(self):
        assert _sanitize_floats(float("inf")) is None

    def test_negative_infinity_replaced_with_none(self):
        assert _sanitize_floats(float("-inf")) is None

    def test_normal_float_unchanged(self):
        assert _sanitize_floats(3.14) == 3.14

    def test_zero_float_unchanged(self):
        assert _sanitize_floats(0.0) == 0.0

    def test_dict_with_nan_values(self):
        result = _sanitize_floats({"a": float("nan"), "b": 1.0, "c": "text"})
        assert result == {"a": None, "b": 1.0, "c": "text"}

    def test_nested_dict(self):
        result = _sanitize_floats({"outer": {"inner": float("inf")}})
        assert result == {"outer": {"inner": None}}

    def test_list_with_nan(self):
        result = _sanitize_floats([1.0, float("nan"), 3.0])
        assert result == [1.0, None, 3.0]

    def test_list_of_dicts(self):
        rows = [
            {"val": float("nan"), "name": "a"},
            {"val": 5.0, "name": "b"},
        ]
        result = _sanitize_floats(rows)
        assert result[0]["val"] is None
        assert result[1]["val"] == 5.0

    def test_non_float_types_unchanged(self):
        assert _sanitize_floats("hello") == "hello"
        assert _sanitize_floats(42) == 42
        assert _sanitize_floats(None) is None
        assert _sanitize_floats(True) is True

    def test_tuple_converted_to_list(self):
        result = _sanitize_floats((float("nan"), 1.0))
        assert result == [None, 1.0]


class TestSafeJsonDumps:
    def test_produces_valid_json_with_nan(self):
        data = {"value": float("nan"), "label": "test"}
        result = _safe_json_dumps(data)
        parsed = json.loads(result)
        assert parsed["value"] is None
        assert parsed["label"] == "test"

    def test_produces_valid_json_with_infinity(self):
        data = {"pos": float("inf"), "neg": float("-inf")}
        result = _safe_json_dumps(data)
        parsed = json.loads(result)
        assert parsed["pos"] is None
        assert parsed["neg"] is None

    def test_handles_non_serializable_with_default_str(self):
        from datetime import date
        data = {"date": date(2024, 1, 15)}
        result = _safe_json_dumps(data)
        parsed = json.loads(result)
        assert parsed["date"] == "2024-01-15"

    def test_sql_result_with_nan_row(self):
        """Simulate a real SQL result containing NaN from PostgreSQL."""
        tool_result = {
            "success": True,
            "result": [
                {"artist": "Test", "score": float("nan"), "count": 5},
                {"artist": "Other", "score": 0.95, "count": 10},
            ],
            "row_count": 2,
            "sql": "SELECT artist, score, count FROM stats",
            "error": None,
        }
        result = _safe_json_dumps(tool_result)
        parsed = json.loads(result)
        assert parsed["result"][0]["score"] is None
        assert parsed["result"][1]["score"] == 0.95
