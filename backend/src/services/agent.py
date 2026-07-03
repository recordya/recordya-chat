"""Agentic service - generic tool loop for any data source type.

This service is GENERIC - it knows nothing about specific data sources.
All domain knowledge comes from plugin implementations.

Implements the Anthropic-style agentic loop:
1. Send user question + tools to LLM
2. If LLM returns tool_calls, execute them via plugin
3. Send results back to LLM
4. Repeat until LLM gives final text response

Uses streaming (SSE) for real-time UI updates.

Supports both:
- ManagedPlugin (service runs tool loop)
- ExecutablePlugin (plugin has full control)
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import ExitStack
from typing import Any

from langfuse import propagate_attributes

from src.core.config import settings
from src.core.engine import CoreEngine
from src.core.exceptions import LLMError
from src.core.global_tools import get_global_tool_registry
from src.core.i18n import translate
from src.core.langfuse import get_langfuse
from src.core.protocols import BasePlugin, ExecutablePlugin, ManagedPlugin
from src.llm.client import LlmFacade
from src.plugin_sdk.sql import BaseSQLPlugin
from src.services.agent_helpers import (
    CompositeToolProvider,
    ConversationBuilder,
    ToolExecutionService,
)
from src.services.factory import get_engine
from src.services.leaked_tool_guard import LeakedToolGuard

logger = logging.getLogger(__name__)

# Configuration
MAX_ITERATIONS = settings.MAX_ITERATIONS  # Safety limit for agentic loop (configurable via .env)
TOOL_TIMEOUT = 30  # Timeout for single tool execution (seconds)
_FALLBACK_CONTENT = translate("agent.fallback_content")

# User-friendly error messages for known LLM/API error patterns.
# Each entry is (substring_to_match, message_key); the message is localized
# via translate() using the configured locale.
_FRIENDLY_ERROR_KEYS: list[tuple[str, str]] = [
    ("could not parse the json body", "agent.error.json_body"),
    ("context_length_exceeded", "agent.error.context_length"),
    ("rate_limit", "agent.error.rate_limit"),
    ("server_error", "agent.error.server_error"),
    ("timeout", "agent.error.timeout"),
]

# Substrings that indicate a transient / retryable LLM error.
_RETRYABLE_PATTERNS: list[str] = [
    "could not parse the json body",
    "server_error",
    "timeout",
    "502",
    "503",
    "overloaded",
]

_AUTO_RETRY_DELAY_SECONDS = 1.0


def _friendly_error_message(raw: str) -> str:
    """Map a raw exception message to a localized, user-friendly message."""
    lower = raw.lower()
    for pattern, key in _FRIENDLY_ERROR_KEYS:
        if pattern in lower:
            return translate(key)
    return translate("agent.error.generic")


def _is_retryable_error(error: Exception) -> bool:
    """Return True if the error looks transient and worth one automatic retry."""
    lower = str(error).lower()
    return any(pattern in lower for pattern in _RETRYABLE_PATTERNS)

# Default status hints for tools without explicit status_hint
# Plugin tools can override by setting status_hint in their definition
DEFAULT_STATUS_HINTS = {
    "get_schema": translate("agent.status.get_schema"),
    "execute_query": translate("agent.status.execute_query"),
    "generate_custom_sql": translate("agent.status.generate_custom_sql"),
    "semantic_search": translate("agent.status.semantic_search"),
}


def _is_widget_row(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    widget_type = value.get("_widget_type")
    return isinstance(widget_type, str) and bool(widget_type.strip())


def _has_renderable_results(tool_history: list[dict[str, Any]]) -> bool:
    latest_successful: dict[str, Any] | None = None

    for entry in reversed(tool_history):
        tool_result = entry.get("result")
        if not isinstance(tool_result, dict) or tool_result.get("success") is not True:
            continue

        if latest_successful is None:
            latest_successful = tool_result

        result_rows = tool_result.get("result")
        if isinstance(result_rows, list) and any(_is_widget_row(row) for row in result_rows):
            return True

    if latest_successful is None:
        return False

    result_rows = latest_successful.get("result")
    return isinstance(result_rows, list) and len(result_rows) > 0


def _get_latest_user_notice(tool_history: list[dict[str, Any]]) -> str | None:
    for entry in reversed(tool_history):
        tool_result = entry.get("result")
        if not isinstance(tool_result, dict) or tool_result.get("success") is not True:
            continue

        user_notice = tool_result.get("user_notice")
        if isinstance(user_notice, str) and user_notice.strip():
            return user_notice.strip()

    return None


def _merge_user_notice(content: str | None, tool_history: list[dict[str, Any]]) -> str:
    final_content = content or ""
    user_notice = _get_latest_user_notice(tool_history)
    if not user_notice:
        return final_content

    if user_notice.casefold() in final_content.casefold():
        return final_content

    if not final_content:
        return user_notice

    return f"{user_notice} {final_content}"


class AgentService:
    """Generic agentic service for any data source plugin.

    Supports two plugin types:
    - ExecutablePlugin: Plugin has full control, runs its own logic
    - ManagedPlugin: Service runs the agentic tool loop

    The service itself contains NO domain-specific logic.
    """

    def __init__(
        self,
        plugin: BasePlugin,
        llm_provider: LlmFacade,
        engine: CoreEngine | None = None,
    ):
        """Initialize agent service.

        Args:
            plugin: Plugin providing context and tools
            llm_provider: LLM facade for generating responses
            engine: Optional CoreEngine (defaults to singleton)
        """
        self.plugin = plugin
        self.llm = llm_provider
        self._engine = engine

    @property
    def engine(self) -> CoreEngine:
        """Get CoreEngine, creating if needed."""
        if self._engine is None:
            self._engine = get_engine()
        return self._engine

    def _is_executable_plugin(self) -> bool:
        """Check if plugin is an ExecutablePlugin."""
        return isinstance(self.plugin, ExecutablePlugin)

    def _build_result(
        self,
        content: str | None,
        tool_history: list[dict[str, Any]],
        iterations: int,
        error: str | None = None,
        langfuse_trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Factory for agent run result."""
        return {
            "content": content,
            "tool_history": tool_history,
            "iterations": iterations,
            "source_type": getattr(self.plugin, "source_type", "unknown"),
            "error": error,
            "langfuse_trace_id": langfuse_trace_id,
        }

    @staticmethod
    def _start_langfuse_run(
        plugin: BasePlugin,
        model: str,
        question: str,
        user_id: str | None,
        session_id: str | None,
    ) -> "_LangfuseRun":
        """Create a _LangfuseRun that wraps all Langfuse lifecycle."""
        return _LangfuseRun(plugin, model, question, user_id, session_id)

    async def run(
        self,
        question: str,
        conversation_history: list[dict[str, Any]] | None = None,
        model: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run plugin with streaming status updates via SSE.

        For ExecutablePlugin: Delegates to plugin.run()
        For ManagedPlugin: Runs the service-managed agentic tool loop

        Args:
            question: User's question in natural language
            conversation_history: Previous messages for context
            model: LLM model to use
            user_id: Optional user ID for Langfuse tracking
            session_id: Optional session ID for Langfuse grouping

        Yields:
            Dictionary events with type and data:
            - {"type": "status", "data": {"message": str, "step": int, ...}}
            - {"type": "tool", "data": {"name": str, "duration_ms": int, ...}}
            - {"type": "complete", "data": AgentResponse}
            - {"type": "error", "data": {"message": str}}

        Events always carry full execution detail; redaction for non-admin
        consumers is the responsibility of the API/SSE layer.
        """
        if not question or not isinstance(question, str):
            yield {
                "type": "error",
                "data": {"message": translate("agent.error.missing_question")},
            }
            return

        model = model or settings.DEFAULT_LLM_MODEL

        # Route to appropriate implementation
        if self._is_executable_plugin():
            async for event in self._run_executable_plugin(
                question=question,
                conversation_history=conversation_history,
                model=model,
                user_id=user_id,
                session_id=session_id,
            ):
                yield event
        else:
            async for event in self._run_managed_plugin(
                question=question,
                conversation_history=conversation_history,
                model=model,
                user_id=user_id,
                session_id=session_id,
            ):
                yield event

    async def _run_executable_plugin(
        self,
        question: str,
        conversation_history: list[dict[str, Any]] | None,
        model: str,
        user_id: str | None,
        session_id: str | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run an ExecutablePlugin - plugin has full control.

        Core manages session lifecycle, plugin manages execution.
        """
        plugin = self.plugin
        assert isinstance(plugin, ExecutablePlugin)

        effective_session_id = session_id or f"session_{id(self)}"

        # Start session (observability trace)
        await self.engine.start_session(
            effective_session_id,
            plugin.name,
            question,
            user_id=user_id,
        )

        try:
            # Plugin runs with full control
            async for event in plugin.run(
                engine=self.engine,
                question=question,
                session_id=effective_session_id,
                model=model,
                conversation_history=conversation_history,
                user_id=user_id,
            ):
                yield event

        except Exception as e:
            logger.error(f"ExecutablePlugin error: {e}")
            # Log error to trace
            if self.engine._observability and self.engine._current_trace:
                self.engine._observability.log_error(self.engine._current_trace, str(e))
            yield self.engine.emit_error(str(e))

        finally:
            # End session (close trace)
            await self.engine.end_session()

    async def _run_managed_plugin(
        self,
        question: str,
        conversation_history: list[dict[str, Any]] | None,
        model: str,
        user_id: str | None,
        session_id: str | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run a ManagedPlugin with service-managed tool loop."""
        plugin = self.plugin
        assert isinstance(plugin, ManagedPlugin)

        lf_run = self._start_langfuse_run(plugin, model, question, user_id, session_id)

        # Initial status
        yield {
            "type": "status",
            "data": {"message": translate("agent.status.analyzing"), "step": 0},
        }

        # Build initial messages via shared builder
        builder = ConversationBuilder(plugin)
        messages = await builder.build_messages(question, conversation_history)

        # Get tools from plugin merged with opted-in global tools
        tool_provider = CompositeToolProvider(plugin, get_global_tool_registry())
        tools = tool_provider.get_tools_definition()

        leaked_guard = LeakedToolGuard.from_tools(tools)

        # Build request parameters (policy applied in LlmFacade)
        kwargs: dict[str, Any] = {}

        # Track tool executions
        tool_history: list[dict[str, Any]] = []
        iterations = 0
        tool_executor = ToolExecutionService(
            tool_provider,
            lf_run._langfuse,
            question=question,
            conversation_history=conversation_history,
        )

        try:
            effective_model = model
            request_overrides: dict[str, Any] = {}
            # Agentic loop
            while iterations < MAX_ITERATIONS:
                iterations += 1
                logger.debug(f"Agent iteration {iterations}")

                # Stream text deltas to UI; only ``tool_calls`` (which drive
                # widget generation) are kept off the token channel. The
                # per-iteration ``seen_tool_calls`` guard inside ``_stream_llm``
                # is responsible for that suppression — the assistant's
                # commentary around widgets still streams normally.

                # Call LLM (streaming). One automatic retry for transient
                # errors is allowed only when no tokens have been emitted yet.
                response: dict[str, Any] | None = None
                tokens_emitted = False
                iteration_streamed_tokens = False
                for attempt in range(2):
                    try:
                        async for sse_event, final_response in self._stream_llm(
                            messages=messages,
                            model=model,
                            tools=tools,
                            kwargs=kwargs,
                        ):
                            if sse_event is not None:
                                tokens_emitted = True
                                iteration_streamed_tokens = True
                                yield sse_event
                            if final_response is not None:
                                response = final_response
                        break
                    except Exception as llm_err:
                        if (
                            attempt == 0
                            and not tokens_emitted
                            and _is_retryable_error(llm_err)
                        ):
                            logger.warning(
                                "Retryable LLM error (auto-retry in %.1fs): %s",
                                _AUTO_RETRY_DELAY_SECONDS,
                                llm_err,
                            )
                            await asyncio.sleep(_AUTO_RETRY_DELAY_SECONDS)
                            continue
                        raise
                assert response is not None

                tool_calls = response.get("tool_calls")
                content = response.get("content")
                effective_model = str(response.get("model") or effective_model)
                response_overrides = response.get("request_overrides")
                if isinstance(response_overrides, dict):
                    if "temperature" in response_overrides:
                        request_overrides["temperature"] = response_overrides["temperature"]
                    if "seed" in response_overrides:
                        request_overrides["seed"] = response_overrides["seed"]

                # Leaked tool-call guard: retry once, then sanitize
                if not tool_calls and leaked_guard.should_retry(content):
                    if iteration_streamed_tokens:
                        # Tokens of the leaked draft were already streamed;
                        # tell the UI to discard them before the retry.
                        yield {"type": "token_reset", "data": {}}
                    leaked_guard.append_correction(messages, content)
                    continue

                # If no tool calls, we have final response
                if not tool_calls:
                    final_content = leaked_guard.finalize(content)
                    if not final_content and not _has_renderable_results(tool_history):
                        final_content = _FALLBACK_CONTENT
                    final_content = _merge_user_notice(final_content, tool_history)

                    logger.info(
                        "Emitting complete event: iterations=%s tool_count=%s trace_id=%s",
                        iterations,
                        len(tool_history),
                        lf_run.trace_id,
                    )
                    lf_run.finish(output={
                        "content": final_content,
                        "iterations": iterations,
                        "tool_count": len(tool_history),
                        "effective_model": effective_model,
                        "request_overrides": request_overrides or None,
                    })
                    yield {
                        "type": "complete",
                        "data": self._build_result(
                            final_content,
                            tool_history, iterations,
                            langfuse_trace_id=lf_run.trace_id,
                        ),
                    }
                    return

                # Process tool calls
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
                messages.append(assistant_msg)

                parsed_calls = tool_executor.parse_tool_calls(tool_calls)
                for call in parsed_calls:
                    reasoning = call["arguments"].pop("reasoning", None)
                    status_message = reasoning or self._get_status_hint(
                        call["tool_name"], tools
                    )
                    yield {
                        "type": "status",
                        "data": {
                            "message": status_message,
                            "step": iterations,
                            "tool_id": call["tool_id"],
                            "tool_name": call["tool_name"],
                            "arguments": call["arguments"],
                            "reasoning": reasoning,
                        },
                    }

                executed = await tool_executor.execute_parsed_calls(
                    parsed_calls=parsed_calls,
                    messages=messages,
                    tool_history=tool_history,
                )

                for parsed, entry in zip(parsed_calls, executed, strict=True):
                    result = entry.get("result") or {}
                    yield {
                        "type": "tool",
                        "data": {
                            "name": entry["tool"],
                            "duration_ms": entry["duration_ms"],
                            "tool_id": parsed["tool_id"],
                            "success": result.get("success"),
                            "row_count": result.get("row_count"),
                            "error": result.get("error"),
                            "result": result,
                        },
                    }

            # Max iterations reached
            logger.warning(f"Agent reached max iterations ({MAX_ITERATIONS})")
            lf_run.finish(level="WARNING", status_message="max_iterations_reached")
            yield {
                "type": "complete",
                "data": self._build_result(
                    translate("agent.error.max_iterations"),
                    tool_history,
                    iterations,
                    error="max_iterations_reached",
                    langfuse_trace_id=lf_run.trace_id,
                ),
            }

        except LLMError as e:
            logger.error(f"LLM error: {e}")
            lf_run.finish(level="ERROR", status_message=str(e))
            logger.info("Emitting error event (LLMError): trace_id=%s", lf_run.trace_id)
            yield {
                "type": "error",
                "data": {
                    "message": _friendly_error_message(str(e)),
                    "langfuse_trace_id": lf_run.trace_id,
                },
            }
        except Exception as e:
            logger.error(f"Agent error: {e}")
            lf_run.finish(level="ERROR", status_message=str(e))
            logger.info("Emitting error event (Exception): trace_id=%s", lf_run.trace_id)
            yield {
                "type": "error",
                "data": {
                    "message": _friendly_error_message(str(e)),
                    "langfuse_trace_id": lf_run.trace_id,
                },
            }
        finally:
            # Covers task cancellation (CancelledError, BaseException) when the
            # SSE consumer disconnects mid-stream — the regular except branches
            # do not catch BaseException, so the trace would otherwise leak.
            # finish() is idempotent, so happy/error paths above remain authoritative.
            if not lf_run.finished:
                lf_run.finish(level="WARNING", status_message="cancelled")

    def _get_status_hint(
        self, tool_name: str, tools: list[dict[str, Any]]
    ) -> str:
        """Get status hint for a tool from the provided definitions or defaults."""
        for tool in tools:
            func = tool.get("function", {})
            if func.get("name") == tool_name:
                status_hint = tool.get("status_hint")
                if status_hint:
                    return status_hint

        # Fallback to default hints
        return DEFAULT_STATUS_HINTS.get(tool_name, translate("agent.status.default"))

    async def _stream_llm(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> AsyncGenerator[tuple[dict[str, Any] | None, dict[str, Any] | None], None]:
        """Consume one LLM streaming call, yielding ``(sse_event, final)`` tuples.

        ``sse_event`` is a token event ready to forward to the SSE stream
        (or ``None`` if this chunk should not be exposed to the UI).
        ``final`` is the aggregated response dict (same shape as
        :meth:`LlmFacade.complete` returns) emitted exactly once at the end.

        Text deltas are forwarded as ``token`` events; tool-call deltas
        (which drive widget generation) are never streamed and additionally
        suppress any further content in the same iteration to avoid leaking
        partial JSON arguments into the chat.
        """
        seen_tool_calls = False
        chunks = self._iter_llm_chunks(messages, model, tools, kwargs)
        async for chunk in chunks:
            chunk_type = chunk.get("type")
            if chunk_type == "tool_call_started":
                seen_tool_calls = True
                yield None, None
            elif chunk_type == "content":
                delta = chunk.get("delta") or ""
                if not delta or seen_tool_calls:
                    yield None, None
                    continue
                yield {"type": "token", "data": {"delta": delta}}, None
            elif chunk_type == "final":
                final_response = {k: v for k, v in chunk.items() if k != "type"}
                if final_response.get("tool_calls"):
                    seen_tool_calls = True
                yield None, final_response

    async def _iter_llm_chunks(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]],
        kwargs: dict[str, Any],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield LLM stream chunks, falling back to ``complete`` when needed.

        Returns the same chunk shape as :meth:`BaseLLMProvider.stream`:
        ``{"type": "content", "delta": str}``, ``{"type": "tool_call_started"}``,
        ``{"type": "final", **response}``.
        """
        stream_fn = getattr(self.llm, "stream", None)
        if stream_fn is not None:
            async for chunk in stream_fn(
                messages=messages,
                model=model,
                tools=tools,
                tool_choice="auto",
                purpose="agent",
                **kwargs,
            ):
                yield chunk
            return

        response = await self.llm.complete(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice="auto",
            purpose="agent",
            **kwargs,
        )
        yield {"type": "final", **response}



class _LangfuseRun:
    """Encapsulates Langfuse trace lifecycle for a single agent run.

    Manages the observation context (``start_as_current_observation``) and
    attribute propagation (``propagate_attributes``) so that the
    ``langfuse.openai`` auto-instrumentation nests OpenAI calls under
    the correct trace with ``user_id`` and ``session_id``.
    """

    def __init__(
        self,
        plugin: BasePlugin,
        model: str,
        question: str,
        user_id: str | None,
        session_id: str | None,
    ) -> None:
        self.span: Any = None
        self.trace_id: str | None = None
        self._langfuse = get_langfuse()
        self._stack = ExitStack()
        self._finished = False

        if not self._langfuse:
            return

        try:
            prompt_hash = (
                plugin.get_prompt_hash() if isinstance(plugin, BaseSQLPlugin) else None
            )
            metadata = {
                "requested_model": model,
                "plugin": plugin.name,
                "source_type": getattr(plugin, "source_type", "unknown"),
                "environment": settings.ENV,
                **({"prompt_hash": prompt_hash} if prompt_hash else {}),
            }
            obs_ctx = self._langfuse.start_as_current_observation(
                as_type="span",
                name="agent_run",
                input={"question": question},
                metadata=metadata,
            )
            self.span = self._stack.enter_context(obs_ctx)
            self.trace_id = self.span.trace_id
            self._stack.enter_context(
                propagate_attributes(user_id=user_id, session_id=session_id)
            )
            logger.info("Langfuse trace started: session=%s user=%s", session_id, user_id)
        except Exception as exc:
            logger.warning("Failed to create Langfuse trace: %s", exc)
            self._stack.close()
            self.span = None

    @property
    def finished(self) -> bool:
        return self._finished

    def finish(
        self,
        output: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        """End the span, close contexts, and flush. Idempotent."""
        if self._finished:
            return
        self._finished = True
        if self.span:
            kwargs: dict[str, Any] = {}
            if output:
                kwargs["output"] = output
            if level:
                kwargs["level"] = level
            if status_message:
                kwargs["status_message"] = status_message
            if kwargs:
                self.span.update(**kwargs)
            self.span.end()
        self._stack.close()
        if self._langfuse:
            self._langfuse.flush()
