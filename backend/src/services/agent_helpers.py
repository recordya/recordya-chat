"""Helper services for agent execution."""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from typing import Any, Literal

from src.core.config import settings
from src.core.protocols import ContextConfig, ManagedPlugin

logger = logging.getLogger(__name__)

_TurnMode = Literal["full", "degraded", "text_only"]


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

    async def build_messages(
            self, question: str, conversation_history: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        # Plugin builds complete system prompt (including dynamic data)
        system_prompt = await self._plugin.get_system_prompt()

        # Build initial messages
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if not conversation_history:
            messages.append({"role": "user", "content": question})
            return messages

        # New path: any assistant message has toolResults → replay tool-call history
        if self._history_has_tool_results(conversation_history):
            messages.extend(self._build_tool_replay(conversation_history))
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
        """Replay last N turns into LLM messages with a token budget.

        Newest turns get ``full`` mode; if the budget runs low, older turns
        degrade to ``degraded`` (truncated rows) and finally ``text_only``.
        """
        turns = cls._group_into_turns(history)
        turns = turns[-settings.CONVERSATION_MAX_TURNS:]
        if not turns:
            return []

        serialized_by_mode: list[dict[_TurnMode, dict[str, Any]]] = [
            {
                "full": cls._serialize_turn(user, assistant, mode="full"),
                "degraded": cls._serialize_turn(user, assistant, mode="degraded"),
                "text_only": cls._serialize_turn(user, assistant, mode="text_only"),
            }
            for user, assistant in turns
        ]

        budget = settings.CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET
        selected: list[_TurnMode] = ["text_only"] * len(turns)
        for idx in range(len(turns) - 1, -1, -1):
            for mode in ("full", "degraded", "text_only"):
                cost = serialized_by_mode[idx][mode]["tokens"]
                if cost <= budget:
                    selected[idx] = mode
                    budget -= cost
                    break

        out: list[dict[str, Any]] = []
        for idx in range(len(turns)):
            out.extend(serialized_by_mode[idx][selected[idx]]["messages"])
        return out

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
        """Truncate large row lists; keep widget payloads truncated in-place."""
        max_rows = settings.CONVERSATION_DEGRADED_MAX_ROWS
        if not isinstance(result, dict):
            return result
        inner = result.get("result")
        if not isinstance(inner, list) or len(inner) <= max_rows:
            return result
        truncated_inner: list[Any] = []
        for item in inner[:max_rows]:
            truncated_inner.append(item)
        degraded = dict(result)
        degraded["result"] = truncated_inner
        degraded["_truncated"] = True
        degraded["_original_row_count"] = len(inner)
        return degraded

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Cheap token estimate (~4 chars/token). Good enough for budgeting."""
        if not messages:
            return 0
        text = _safe_json_dumps(messages)
        return max(1, len(text) // 4)


class ToolExecutionService:
    """Execute tool calls via plugin and track results."""

    def __init__(
        self,
        plugin: ManagedPlugin,
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
