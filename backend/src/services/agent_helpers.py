"""Helper services for agent execution."""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Literal

from src.core.config import settings
from src.core.global_tools import GlobalToolRegistry
from src.core.protocols import (
    ContextConfig,
    ManagedPlugin,
    ToolProvider,
    tool_definition_name,
)

logger = logging.getLogger(__name__)

_TurnMode = Literal["full", "degraded", "text_only"]


@dataclass(frozen=True)
class ReplayTurnTokenDiagnostics:
    """Token estimates for one replayed conversation turn."""

    full: int
    degraded: int
    text_only: int

    def to_dict(self) -> dict[str, int]:
        return {
            "full": self.full,
            "degraded": self.degraded,
            "text_only": self.text_only,
        }


@dataclass(frozen=True)
class ReplayTurnDiagnostics:
    """Diagnostics for replay mode selection of one conversation turn."""

    turn_index: int
    selected_mode: _TurnMode
    selected_tokens: int
    fits_budget: bool
    tokens: ReplayTurnTokenDiagnostics
    tool_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "selected_mode": self.selected_mode,
            "selected_tokens": self.selected_tokens,
            "fits_budget": self.fits_budget,
            "tokens": self.tokens.to_dict(),
            "tool_count": self.tool_count,
        }


@dataclass(frozen=True)
class ConversationReplayDiagnostics:
    """Structured diagnostics for replayed tool-call conversation history."""

    enabled: bool
    turns_total: int
    turns_replayed: int
    budget_initial: int
    budget_remaining: int
    selected_modes: list[_TurnMode] = field(default_factory=list)
    mode_counts: dict[_TurnMode, int] = field(default_factory=dict)
    over_budget_turns: int = 0
    truncated: bool = False
    turns: list[ReplayTurnDiagnostics] = field(default_factory=list)

    @property
    def degraded_count(self) -> int:
        return self.mode_counts.get("degraded", 0)

    @property
    def text_only_count(self) -> int:
        return self.mode_counts.get("text_only", 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "turns_total": self.turns_total,
            "turns_replayed": self.turns_replayed,
            "budget_initial": self.budget_initial,
            "budget_remaining": self.budget_remaining,
            "selected_modes": list(self.selected_modes),
            "mode_counts": dict(self.mode_counts),
            "over_budget_turns": self.over_budget_turns,
            "truncated": self.truncated,
            "turns": [turn.to_dict() for turn in self.turns],
        }


def _sanitize_floats(obj: Any) -> Any:
    """Replace NaN / Infinity / -Infinity with None so json.dumps produces valid JSON."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_floats(item) for item in obj]
    return obj


def _safe_json_dumps(obj: Any) -> str:
    """Serialize *obj* to a JSON string that is guaranteed to be valid JSON.

    Replaces ``NaN`` / ``Infinity`` with ``null`` and falls back to ``str()``
    for non-serializable types (dates, Decimals, etc.).
    """
    return json.dumps(_sanitize_floats(obj), ensure_ascii=False, default=str)


class ConversationBuilder:
    """Build initial LLM messages with system prompt and history."""

    # Maximum number of result rows to include in the context summary.
    _MAX_SUMMARY_ROWS = 10

    def __init__(self, plugin: ManagedPlugin) -> None:
        self._plugin = plugin
        self._ctx_cfg: ContextConfig | None = (
            plugin.get_context_config()
            if hasattr(plugin, "get_context_config")
            else None
        )
        self.last_replay_diagnostics: ConversationReplayDiagnostics | None = None

    async def build_messages(
            self, question: str, conversation_history: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        self.last_replay_diagnostics = None

        # Plugin builds complete system prompt (including dynamic data)
        system_prompt = await self._plugin.get_system_prompt()

        # Build initial messages
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if not conversation_history:
            messages.append({"role": "user", "content": question})
            return messages

        # New path: any assistant message has toolResults → replay tool-call history
        if self._history_has_tool_results(conversation_history):
            replay_messages, diagnostics = self._build_tool_replay_with_diagnostics(
                conversation_history
            )
            self.last_replay_diagnostics = diagnostics
            messages.extend(replay_messages)
            messages.append({"role": "user", "content": question})
            return messages

        # Legacy path: only text content + optional [CONTEXT:] from queryResults
        all_shown: list[dict[str, Any]] = []
        for msg in conversation_history[-settings.CONVERSATION_MAX_TURNS * 2:]:
            if msg.get("content"):
                role = "user" if msg.get("role") == "user" else "assistant"
                messages.append({"role": role, "content": msg["content"]})

                if role == "assistant" and self._ctx_cfg is not None:
                    self._collect_shown_rows(
                        msg.get("queryResults"), all_shown, self._ctx_cfg,
                    )

        if self._ctx_cfg is not None:
            cumulative_summary = self._build_cumulative_summary(
                all_shown, self._ctx_cfg,
            )
            if cumulative_summary:
                question = f"{cumulative_summary}\n\n{question}"

        messages.append({"role": "user", "content": question})
        return messages

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_query_results(
            query_results: list[dict[str, Any]] | None,
            cfg: ContextConfig,
    ) -> list[dict[str, Any]]:
        """Flatten query results into plain data rows.

        Widget-wrapped results whose ``_widget_type`` is in
        ``cfg.data_widget_types`` are unwrapped from
        ``_widget_payload.rows``.  Unknown or interaction widgets are
        skipped.  Plain rows (no ``_widget_type``) pass through.
        """
        if not query_results:
            return []

        flat_rows: list[dict[str, Any]] = []
        for item in query_results:
            if not isinstance(item, dict):
                continue
            widget_type = item.get("_widget_type")
            if widget_type is not None:
                if widget_type not in cfg.data_widget_types:
                    continue
                payload = item.get("_widget_payload")
                if isinstance(payload, dict):
                    inner_rows = payload.get("rows")
                    if isinstance(inner_rows, list):
                        flat_rows.extend(
                            r for r in inner_rows if isinstance(r, dict)
                        )
                continue
            flat_rows.append(item)
        return flat_rows

    @classmethod
    def _collect_shown_rows(
            cls,
            query_results: list[dict[str, Any]] | None,
            accumulator: list[dict[str, Any]],
            cfg: ContextConfig,
    ) -> None:
        """Unwrap and deduplicate data rows into *accumulator*.

        Deduplicates by ``cfg.primary_key``.
        """
        pk = cfg.primary_key
        seen_ids = {row.get(pk) for row in accumulator if row.get(pk) is not None}

        for row in cls._unwrap_query_results(query_results, cfg):
            vid = row.get(pk)
            if vid is not None and vid in seen_ids:
                continue
            if vid is not None:
                seen_ids.add(vid)
            accumulator.append(row)

    @classmethod
    def _build_cumulative_summary(
            cls,
            all_shown: list[dict[str, Any]],
            cfg: ContextConfig,
    ) -> str:
        """Build a passive context block listing previously shown results.

        The block provides data only — the system prompt decides when to
        apply exclusion (e.g. when the user asks for alternatives).
        Returns an empty string when there is nothing to summarise.
        """
        if not all_shown:
            return ""

        pk = cfg.primary_key
        display = cfg.display_field
        ids: list[str] = []
        labels: list[str] = []
        for row in all_shown[: cls._MAX_SUMMARY_ROWS]:
            vid = row.get(pk)
            name = row.get(display)
            if vid is not None:
                ids.append(str(vid))
                if name:
                    labels.append(f"{name} ({pk}={vid})")

        if not ids:
            return ""

        return f"[CONTEXT: Previously shown: {'; '.join(labels)}.]"

    # ------------------------------------------------------------------
    # Tool-call history replay
    # ------------------------------------------------------------------

    @staticmethod
    def _history_has_tool_results(history: list[dict[str, Any]]) -> bool:
        for msg in history:
            if msg.get("role") == "assistant" and msg.get("toolResults"):
                return True
        return False

    @staticmethod
    def _group_into_turns(
            history: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
        """Group flat history into (user, assistant) turn pairs.

        Tolerates orphan user or assistant messages (pairs them with ``None``).
        """
        turns: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
        current_user: dict[str, Any] | None = None
        for msg in history:
            role = msg.get("role")
            if role == "user":
                if current_user is not None:
                    turns.append((current_user, None))
                current_user = msg
            elif role == "assistant":
                turns.append((current_user, msg))
                current_user = None
        if current_user is not None:
            turns.append((current_user, None))
        return turns

    @classmethod
    def _build_tool_replay(
            cls, history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        messages, _diagnostics = cls._build_tool_replay_with_diagnostics(history)
        return messages

    @classmethod
    def _build_tool_replay_with_diagnostics(
            cls, history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], ConversationReplayDiagnostics]:
        """Replay last N turns into LLM messages with a token budget.

        Newest turns get ``full`` mode; if the budget runs low, older turns
        degrade to ``degraded`` (truncated rows) and finally ``text_only``.
        """
        all_turns = cls._group_into_turns(history)
        turns = all_turns[-settings.CONVERSATION_MAX_TURNS:]
        initial_budget = settings.CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET
        if not turns:
            return [], ConversationReplayDiagnostics(
                enabled=True,
                turns_total=len(all_turns),
                turns_replayed=0,
                budget_initial=initial_budget,
                budget_remaining=initial_budget,
            )

        serialized_by_mode: list[dict[_TurnMode, dict[str, Any]]] = [
            {
                "full": cls._serialize_turn(user, assistant, mode="full"),
                "degraded": cls._serialize_turn(user, assistant, mode="degraded"),
                "text_only": cls._serialize_turn(user, assistant, mode="text_only"),
            }
            for user, assistant in turns
        ]

        budget = initial_budget
        selected: list[_TurnMode] = ["text_only"] * len(turns)
        turn_diagnostics: list[ReplayTurnDiagnostics | None] = [None for _ in turns]
        for idx in range(len(turns) - 1, -1, -1):
            selected_mode: _TurnMode | None = None
            selected_cost: int | None = None
            for mode in ("full", "degraded", "text_only"):
                cost = serialized_by_mode[idx][mode]["tokens"]
                if cost <= budget:
                    selected[idx] = mode
                    budget -= cost
                    selected_mode = mode
                    selected_cost = cost
                    break
            selected_fits_budget = selected_mode is not None
            if selected_mode is None:
                selected_mode = "text_only"
                selected_cost = serialized_by_mode[idx]["text_only"]["tokens"]

            assistant_msg = turns[idx][1]
            tool_results = (
                assistant_msg.get("toolResults")
                if isinstance(assistant_msg, dict)
                else None
            )
            turn_diagnostics[idx] = ReplayTurnDiagnostics(
                turn_index=idx,
                selected_mode=selected_mode,
                selected_tokens=selected_cost,
                fits_budget=selected_fits_budget,
                tokens=ReplayTurnTokenDiagnostics(
                    full=serialized_by_mode[idx]["full"]["tokens"],
                    degraded=serialized_by_mode[idx]["degraded"]["tokens"],
                    text_only=serialized_by_mode[idx]["text_only"]["tokens"],
                ),
                tool_count=len(tool_results) if isinstance(tool_results, list) else 0,
            )

        out: list[dict[str, Any]] = []
        for idx in range(len(turns)):
            out.extend(serialized_by_mode[idx][selected[idx]]["messages"])

        resolved_turn_diagnostics = [turn for turn in turn_diagnostics if turn is not None]
        mode_counts = dict(Counter(selected))
        over_budget_turns = sum(
            1 for turn in resolved_turn_diagnostics if not turn.fits_budget
        )
        diagnostics = ConversationReplayDiagnostics(
            enabled=True,
            turns_total=len(all_turns),
            turns_replayed=len(turns),
            budget_initial=initial_budget,
            budget_remaining=budget,
            selected_modes=selected,
            mode_counts=mode_counts,
            over_budget_turns=over_budget_turns,
            truncated=any(mode != "full" for mode in selected),
            turns=resolved_turn_diagnostics,
        )
        return out, diagnostics

    @classmethod
    def _serialize_turn(
            cls,
            user_msg: dict[str, Any] | None,
            assistant_msg: dict[str, Any] | None,
            mode: _TurnMode,
    ) -> dict[str, Any]:
        """Serialize one turn into OpenAI messages plus an estimated token cost."""
        messages: list[dict[str, Any]] = []
        if user_msg is not None and user_msg.get("content"):
            messages.append({"role": "user", "content": user_msg["content"]})

        if assistant_msg is None:
            return {"messages": messages, "tokens": cls._estimate_tokens(messages)}

        assistant_content = assistant_msg.get("content") or ""
        tool_results = assistant_msg.get("toolResults") or []

        if not tool_results or mode == "text_only":
            if assistant_content:
                messages.append({"role": "assistant", "content": assistant_content})
            return {"messages": messages, "tokens": cls._estimate_tokens(messages)}

        for tr in tool_results:
            tc = cls._synthesize_tool_calls([tr])[0]
            messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [tc],
            })
            result = tr.get("result")
            if mode == "degraded":
                result = cls._degrade_result(result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": _safe_json_dumps(result),
            })
        if assistant_content:
            messages.append({"role": "assistant", "content": assistant_content})
        return {"messages": messages, "tokens": cls._estimate_tokens(messages)}

    @staticmethod
    def _synthesize_tool_calls(
            tool_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for tr in tool_results:
            tool_call_id = tr.get("tool_call_id") or f"call_{uuid.uuid4().hex[:12]}"
            tool_name = tr.get("tool_name") or tr.get("tool") or ""
            arguments = tr.get("arguments") or {}
            out.append({
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": _safe_json_dumps(arguments),
                },
            })
        return out

    @staticmethod
    def _degrade_result(result: Any) -> Any:
        """Truncate large row lists in common tool result shapes."""
        max_rows = settings.CONVERSATION_DEGRADED_MAX_ROWS
        if not isinstance(result, dict):
            return result

        degraded: dict[str, Any] | None = None

        inner = result.get("result")
        if isinstance(inner, list) and len(inner) > max_rows:
            degraded = dict(result)
            degraded["result"] = list(inner[:max_rows])
            degraded["_result_truncated"] = True
            degraded["_original_row_count"] = len(inner)
            degraded["_retained_row_count"] = max_rows

        entries = result.get("entries")
        if isinstance(entries, list) and len(entries) > max_rows:
            if degraded is None:
                degraded = dict(result)
            degraded["entries"] = list(entries[:max_rows])
            degraded["_entries_truncated"] = True
            degraded["_original_entries_count"] = len(entries)
            degraded["_retained_entries_count"] = max_rows

        if degraded is None:
            return result

        degraded["_truncated"] = True
        return degraded

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Cheap token estimate (~4 chars/token). Good enough for budgeting."""
        if not messages:
            return 0
        text = _safe_json_dumps(messages)
        return max(1, len(text) // 4)


class CompositeToolProvider:
    """Merge the active plugin's tools with opted-in global tools.

    Exposes the same tool surface AgentService needs (definitions, argument
    preparation, execution). The active plugin's own tools take priority on
    name collisions. Global tools are opt-in: only names listed in the plugin
    manifest's ``requires_global_tools`` are exposed, so agents are not
    polluted with unrelated tools.
    """

    def __init__(self, plugin: ManagedPlugin, registry: GlobalToolRegistry) -> None:
        self._plugin = plugin
        self._registry = registry
        self._allowed_global_tools = frozenset(
            plugin.get_manifest().get("requires_global_tools") or []
        )

    def get_tools_definition(self) -> list[dict[str, Any]]:
        """Return plugin tools plus opted-in global tools (deduplicated by name)."""
        plugin_tools = self._plugin.get_tools_definition()
        if not self._allowed_global_tools:
            return plugin_tools
        plugin_names = {tool_definition_name(t) for t in plugin_tools}
        global_tools = [
            definition
            for definition in self._registry.get_tools_definition()
            if tool_definition_name(definition) in self._allowed_global_tools
            and tool_definition_name(definition) not in plugin_names
        ]
        return plugin_tools + global_tools

    def prepare_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        question: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Delegate to the plugin hook for its own tools; pass through for global."""
        if self._is_global_call(tool_name):
            return arguments
        return self._plugin.prepare_tool_arguments(
            tool_name=tool_name,
            arguments=arguments,
            question=question,
            conversation_history=conversation_history,
        )

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Route to the global registry for opted-in tools, otherwise the plugin."""
        if self._is_global_call(tool_name):
            return await self._registry.execute(tool_name, arguments)
        return await self._plugin.execute_tool(tool_name, arguments)

    def _is_global_call(self, tool_name: str) -> bool:
        """A call routes to the registry only for opted-in, non-local tools."""
        if not self._allowed_global_tools:
            return False
        if tool_name not in self._allowed_global_tools:
            return False
        if not self._registry.has_tool(tool_name):
            return False
        plugin_names = {
            tool_definition_name(t) for t in self._plugin.get_tools_definition()
        }
        return tool_name not in plugin_names


class ToolExecutionService:
    """Execute tool calls via plugin and track results."""

    def __init__(
        self,
        plugin: ToolProvider,
        langfuse: Any | None,
        question: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> None:
        self._plugin = plugin
        self._langfuse = langfuse
        self._question = question
        self._conversation_history = conversation_history

    def parse_tool_calls(
            self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            tool_id = tool_call.get("id", "")
            function = tool_call.get("function", {})
            tool_name = function.get("name", "")

            # Parse arguments
            try:
                arguments = json.loads(function.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}

            parsed.append(
                {"tool_id": tool_id, "tool_name": tool_name, "arguments": arguments}
            )
        return parsed

    async def execute_parsed_calls(
            self,
            parsed_calls: list[dict[str, Any]],
            messages: list[dict[str, Any]],
            tool_history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        executed: list[dict[str, Any]] = []
        for call in parsed_calls:
            tool_id = call["tool_id"]
            tool_name = call["tool_name"]
            arguments = self._plugin.prepare_tool_arguments(
                tool_name=tool_name,
                arguments=dict(call["arguments"]),
                question=self._question,
                conversation_history=self._conversation_history,
            )

            logger.info(f"Executing tool: {tool_name}")
            start_time = time.time()

            # Create Langfuse span for tool execution
            tool_span = None
            if self._langfuse:
                try:
                    tool_span = self._langfuse.start_span(
                        name=f"tool_{tool_name}",
                        input=arguments if arguments else {"tool": tool_name},
                    )
                except Exception as e:
                    logger.warning(f"Failed to create tool span: {e}")

            # Execute via plugin
            result = await self._plugin.execute_tool(tool_name, arguments)

            duration_ms = int((time.time() - start_time) * 1000)

            # End tool span with result
            if tool_span:
                try:
                    tool_span.update(
                        output={
                            "success": result.get("success"),
                            "row_count": result.get("row_count"),
                            "sql": result.get("sql"),
                            "tool_type": result.get("tool_type"),
                            "error": result.get("error"),
                        },
                        metadata={"duration_ms": duration_ms},
                    )
                    tool_span.end()
                except Exception as e:
                    logger.warning(f"Failed to end tool span: {e}")

            # Track in history
            entry = {
                "tool": tool_name,
                "tool_call_id": tool_id,
                "arguments": arguments,
                "result": result,
                "duration_ms": duration_ms,
            }
            tool_history.append(entry)
            executed.append(entry)

            # Add tool result message
            tool_result_msg = {
                "role": "tool",
                "tool_call_id": tool_id,
                "content": _safe_json_dumps(result),
            }
            messages.append(tool_result_msg)

            logger.debug(f"Tool {tool_name} completed in {duration_ms}ms")

        return executed
