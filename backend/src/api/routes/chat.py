"""Chat and query endpoints."""

import json
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from src.api.dependencies import (
    AuthServiceDep,
    CurrentUser,
    DBSession,
    LLMProviderDep,
)
from src.core.exceptions import rate_limited
from src.core.i18n import translate
from src.core.protocols import BasePlugin
from src.core.registry import access_guards, datasources
from src.core.roles import is_super_admin
from src.db.models import Chat
from src.services.agent import AgentService
from src.services.app_settings import get_selected_model

router = APIRouter()


class Message(BaseModel):
    """Chat message."""
    role: str
    content: str
    queryResults: list[dict[str, Any]] | None = None
    toolResults: list[dict[str, Any]] | None = None


# Constants for validation (also used by frontend)
QUESTION_MAX_LENGTH = 4000


class AgentRequest(BaseModel):
    """Request for agentic chat."""
    question: str = Field(..., min_length=1, max_length=QUESTION_MAX_LENGTH)
    conversationHistory: list[Message] | None = None
    model: str | None = None
    datasource: str | None = None
    chat_id: str | None = None  # For Langfuse session grouping

    def get_history_dicts(self) -> list[dict[str, Any]] | None:
        """Convert conversation history to list of dicts.

        For assistant messages, forwards ``toolResults`` consumed by
        ``ConversationBuilder`` for native tool-call replay (tool_calls are
        synthesized in-flight from tool_results), and the legacy
        ``queryResults`` used for backward-compatible context injection.
        """
        if not self.conversationHistory:
            return None
        out: list[dict[str, Any]] = []
        for m in self.conversationHistory:
            entry: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.role == "assistant":
                if m.queryResults:
                    entry["queryResults"] = m.queryResults
                if m.toolResults:
                    entry["toolResults"] = m.toolResults
            out.append(entry)
        return out


class ToolExecution(BaseModel):
    """Single tool execution record."""
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    duration_ms: int


class AgentResponse(BaseModel):
    """Response from agentic chat."""
    content: str | None = None
    tool_history: list[ToolExecution] = []
    iterations: int = 0
    source_type: str | None = None
    error: str | None = None


def _get_plugin(name: str | None = None) -> BasePlugin | None:
    """Get data source plugin by name or first available."""
    if name and datasources.has_instance(name):
        return datasources.get_instance(name)
    # Fall back to first available
    instances = datasources.list_instances()
    if instances:
        return datasources.get_instance(instances[0])
    return None


# Public keys allowed in SSE payloads for non-super-admin users.
_PUBLIC_STATUS_KEYS = frozenset({"message", "step"})
_PUBLIC_TOOL_KEYS = frozenset({"name", "duration_ms"})


def _redact_event(event: dict[str, Any], is_super: bool) -> dict[str, Any]:
    """Filter event payload to public fields for non-super-admin consumers.

    ``super_admin`` gets the full event verbatim; everyone else sees only
    minimal, user-facing progress info (no tool ids, arguments, results).

    ``token`` and ``token_reset`` events are pure UX signals carrying only
    the streamed assistant text (or a reset marker) and are always public.
    """
    if is_super:
        return event
    event_type = event.get("type")
    data = event.get("data", {})
    if event_type == "status" and isinstance(data, dict):
        public = {k: v for k, v in data.items() if k in _PUBLIC_STATUS_KEYS}
        return {"type": "status", "data": public}
    if event_type == "tool" and isinstance(data, dict):
        public = {k: v for k, v in data.items() if k in _PUBLIC_TOOL_KEYS}
        return {"type": "tool", "data": public}
    return event


@router.post("/agent/stream")
async def agent_stream(
    request: AgentRequest,
    current_user: CurrentUser,
    auth_service: AuthServiceDep,
    llm: LLMProviderDep,
    db: DBSession,
) -> EventSourceResponse:
    """Streaming agentic chat endpoint with real-time status updates via SSE.

    Returns Server-Sent Events stream with the following event types:
    - status: Real-time status updates (e.g., "Analizuję pytanie...")
    - tool: Information about executed tools
    - complete: Final response with full AgentResponse data
    - error: Error message if something goes wrong

    Use this endpoint for better UX with real-time feedback.
    """
    # Materialise user attributes before guards — a guard may rollback the
    # session (e.g. when the table doesn't exist yet), which would expire
    # lazy-loaded ORM attributes on current_user.
    user_id = current_user.id
    user_email = current_user.email
    is_super = is_super_admin(current_user.role)

    # If the request targets an existing chat, the chat's stored datasource
    # is authoritative — agent selection is immutable per chat.
    datasource_name = request.datasource
    if request.chat_id:
        try:
            chat_uuid = uuid.UUID(request.chat_id)
        except ValueError:
            chat_uuid = None
        if chat_uuid is not None:
            stored = await db.execute(
                select(Chat.datasource).where(
                    Chat.id == chat_uuid,
                    Chat.user_id == user_id,
                )
            )
            stored_datasource = stored.scalar_one_or_none()
            if stored_datasource:
                datasource_name = stored_datasource

    # Run all registered access guards (plugin-provided). Guards run after the
    # datasource is resolved so per-plugin guards can gate on the target agent.
    for guard in access_guards.get_all_instances().values():
        await guard.check_access(db, user_id, datasource_name)

    # Check rate limit
    usage = await auth_service.check_and_increment_usage(user_id)
    if not usage["allowed"]:
        raise rate_limited(translate("chat.error.rate_limit", limit=usage["limit"]))

    # Get plugin
    plugin = _get_plugin(datasource_name)
    if not plugin:
        async def error_generator():
            yield {
                "event": "error",
                "data": json.dumps({"message": "No data source plugin available"}),
            }

        return EventSourceResponse(error_generator())

    # The persisted admin selection is the source of truth; a model in the
    # request body (if any) takes precedence.
    model = request.model
    if model is None:
        model = await get_selected_model(db)

    async def event_generator():
        service = AgentService(plugin, llm)
        async for event in service.run(
            question=request.question,
            conversation_history=request.get_history_dicts(),
            model=model,
            user_id=user_email,
            session_id=request.chat_id,
        ):
            redacted = _redact_event(event, is_super)
            yield {
                "event": redacted["type"],
                "data": json.dumps(redacted["data"], ensure_ascii=False, default=str),
            }

    return EventSourceResponse(event_generator())
