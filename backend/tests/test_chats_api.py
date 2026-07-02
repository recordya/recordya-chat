"""Tests for chat datasource persistence and authoritative resolution.

Covers:
- POST /api/chats persists the `datasource` field
- GET /api/chats/{id} returns the stored `datasource`
- POST /api/agent/stream uses Chat.datasource over request body when chat_id is given
- POST /api/agent/stream falls back to request.datasource when chat_id is absent
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_auth_service,
    get_current_user,
    get_llm_provider,
    get_user_chat,
)
from src.api.routes.chat import _redact_event
from src.api.routes.chat import router as chat_router
from src.api.routes.chats import router as chats_router
from src.db.app_database import get_db
from src.db.models import Chat, ChatMessage, ChatMessageFeedback

FAKE_USER_ID = uuid.uuid4()


class _FakeUser:
    def __init__(self, uid: uuid.UUID, email: str = "user@test", role: str = "user") -> None:
        self.id = uid
        self.email = email
        self.role = role


def _make_db_for_create() -> AsyncMock:
    db = AsyncMock()
    db.storage = {}

    def _add(chat: Chat) -> None:
        if chat.id is None:
            chat.id = uuid.uuid4()
        db.storage[chat.id] = chat

    async def _refresh(chat: Chat) -> None:
        now = datetime.now(UTC)
        chat.created_at = now
        chat.updated_at = now

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def _build_chats_app() -> FastAPI:
    app = FastAPI()
    app.include_router(chats_router, prefix="/api")
    return app


def _build_chat_app() -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api")
    return app


def _wire_agent_stream_app(app: FastAPI, db: AsyncMock) -> None:
    auth_service = AsyncMock()
    auth_service.check_and_increment_usage = AsyncMock(
        return_value={"allowed": True, "limit": 100}
    )
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_llm_provider] = lambda: MagicMock()


def _make_db_for_message_create() -> AsyncMock:
    db = AsyncMock()
    db.storage = []

    def _add(message: ChatMessage) -> None:
        if message.id is None:
            message.id = uuid.uuid4()
        db.storage.append(message)

    async def _refresh(message: ChatMessage) -> None:
        message.created_at = datetime.now(UTC)

    message_result = _make_scalars_all_result(db.storage)
    feedback_result = _make_scalars_all_result([])

    async def _execute(statement):
        if "message_feedback" in str(statement):
            return feedback_result
        return message_result

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=_refresh)
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_scalars_all_result(items: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items)
    result.scalars = MagicMock(return_value=scalars)
    return result


def _make_scalar_one_or_none_result(item) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=item)
    return result


def _make_db_for_message_list(
    messages: list[ChatMessage],
    feedback: list[ChatMessageFeedback] | None = None,
) -> AsyncMock:
    db = AsyncMock()
    message_result = _make_scalars_all_result(messages)
    feedback_result = _make_scalars_all_result(feedback or [])

    async def _execute(statement):
        if "message_feedback" in str(statement):
            return feedback_result
        return message_result

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_chat() -> Chat:
    chat = Chat(id=uuid.uuid4(), user_id=FAKE_USER_ID, title="t", datasource="ds")
    chat.created_at = datetime.now(UTC)
    chat.updated_at = datetime.now(UTC)
    return chat


def _make_message_with_steps() -> ChatMessage:
    msg = ChatMessage(
        id=uuid.uuid4(),
        chat_id=FAKE_USER_ID,
        role="assistant",
        content="hello",
        sql_query=None,
        results_json=None,
        reasoning_steps=[{"step": 1, "tool_name": "t", "arguments": {"x": 1}}],
    )
    msg.created_at = datetime.now(UTC)
    return msg


def _make_feedback(message: ChatMessage, rating: str = "positive") -> ChatMessageFeedback:
    feedback = ChatMessageFeedback(
        id=uuid.uuid4(),
        message_id=message.id,
        chat_id=message.chat_id,
        user_id=FAKE_USER_ID,
        rating=rating,
        saved_time="up_to_30_min" if rating == "positive" else None,
        comment="Helpful" if rating == "positive" else "Not helpful",
    )
    now = datetime.now(UTC)
    feedback.created_at = now
    feedback.updated_at = now
    return feedback


def _make_db_for_feedback(
    message: ChatMessage,
    feedback: ChatMessageFeedback | None = None,
) -> AsyncMock:
    db = AsyncMock()
    db.storage = [] if feedback is None else [feedback]
    message_result = _make_scalar_one_or_none_result(message)

    def _feedback_result():
        return _make_scalar_one_or_none_result(db.storage[0] if db.storage else None)

    async def _execute(statement):
        if "message_feedback" in str(statement):
            return _feedback_result()
        return message_result

    def _add(item: ChatMessageFeedback) -> None:
        if item.id is None:
            item.id = uuid.uuid4()
        db.storage.append(item)

    async def _refresh(item: ChatMessageFeedback) -> None:
        now = datetime.now(UTC)
        if item.created_at is None:
            item.created_at = now
        item.updated_at = now

    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=_refresh)
    return db


def test_create_chat_persists_datasource() -> None:
    app = _build_chats_app()
    db = _make_db_for_create()
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID)
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app)
    created = client.post(
        "/api/chats",
        json={"title": "New", "datasource": "reports"},
    )

    assert created.status_code == 200
    chat_id = created.json()["id"]
    assert created.json()["datasource"] == "reports"

    app.dependency_overrides[get_user_chat] = lambda: db.storage[uuid.UUID(chat_id)]
    fetched = client.get(f"/api/chats/{chat_id}")

    assert fetched.status_code == 200
    assert fetched.json()["id"] == chat_id
    assert fetched.json()["datasource"] == "reports"


def test_get_chat_returns_datasource() -> None:
    app = _build_chats_app()
    chat_id = uuid.uuid4()
    chat = Chat(id=chat_id, user_id=FAKE_USER_ID, title="X", datasource="metrics")
    chat.created_at = datetime.now(UTC)
    chat.updated_at = datetime.now(UTC)
    app.dependency_overrides[get_user_chat] = lambda: chat

    client = TestClient(app)
    response = client.get(f"/api/chats/{chat_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(chat_id)
    assert body["datasource"] == "metrics"


def test_agent_stream_uses_stored_chat_datasource_over_request() -> None:
    app = _build_chat_app()
    chat_id = uuid.uuid4()
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value="reports")
    db.execute = AsyncMock(return_value=result)
    _wire_agent_stream_app(app, db)

    captured: dict = {}

    def fake_get_plugin(name: str | None):
        captured["name"] = name
        return None

    with patch("src.api.routes.chat._get_plugin", side_effect=fake_get_plugin), \
         patch("src.api.routes.chat.access_guards") as guards:
        guards.get_all_instances.return_value = {}
        response = TestClient(app).post(
            "/api/agent/stream",
            json={"question": "ping", "datasource": "metrics", "chat_id": str(chat_id)},
        )

    assert response.status_code == 200
    assert captured["name"] == "reports"


def test_agent_stream_uses_request_datasource_when_no_chat_id() -> None:
    app = _build_chat_app()
    db = AsyncMock()
    db.execute = AsyncMock()
    _wire_agent_stream_app(app, db)

    captured: dict = {}

    def fake_get_plugin(name: str | None):
        captured["name"] = name
        return None

    with patch("src.api.routes.chat._get_plugin", side_effect=fake_get_plugin), \
         patch("src.api.routes.chat.access_guards") as guards:
        guards.get_all_instances.return_value = {}
        response = TestClient(app).post(
            "/api/agent/stream",
            # An explicit model skips both the chat lookup and the settings lookup.
            json={"question": "ping", "datasource": "metrics", "model": "gpt-5.2"},
        )

    assert response.status_code == 200
    assert captured["name"] == "metrics"
    db.execute.assert_not_called()


def test_create_message_super_admin_persists_reasoning_steps() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    db = _make_db_for_message_create()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(
        FAKE_USER_ID, role="super_admin"
    )
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app)
    steps = [{"step": 1, "tool_name": "t", "result": {"row_count": 3}}]
    created = client.post(
        f"/api/chats/{chat.id}/messages",
        json={"role": "assistant", "content": "x", "reasoning_steps": steps},
    )

    assert created.status_code == 200
    assert created.json()["reasoning_steps"] == steps

    listed = client.get(f"/api/chats/{chat.id}/messages")

    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["reasoning_steps"] == steps


def test_create_message_admin_drops_reasoning_steps() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    db = _make_db_for_message_create()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="admin")
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app)
    created = client.post(
        f"/api/chats/{chat.id}/messages",
        json={
            "role": "assistant",
            "content": "x",
            "reasoning_steps": [{"step": 1, "tool_name": "t"}],
        },
    )

    assert created.status_code == 200
    assert created.json()["reasoning_steps"] is None


def test_create_message_non_super_admin_drops_reasoning_steps() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    db = _make_db_for_message_create()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app)
    created = client.post(
        f"/api/chats/{chat.id}/messages",
        json={
            "role": "assistant",
            "content": "x",
            "reasoning_steps": [{"step": 1, "tool_name": "t"}],
        },
    )

    assert created.status_code == 200
    assert created.json()["reasoning_steps"] is None

    app.dependency_overrides[get_current_user] = lambda: _FakeUser(
        FAKE_USER_ID, role="super_admin"
    )
    listed = client.get(f"/api/chats/{chat.id}/messages")

    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["reasoning_steps"] is None


def test_list_messages_super_admin_sees_reasoning_steps() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    msg = _make_message_with_steps()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(
        FAKE_USER_ID, role="super_admin"
    )
    app.dependency_overrides[get_db] = lambda: _make_db_for_message_list([msg])

    response = TestClient(app).get(f"/api/chats/{chat.id}/messages")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["reasoning_steps"] == msg.reasoning_steps


def test_list_messages_admin_redacts_reasoning_steps() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    msg = _make_message_with_steps()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="admin")
    app.dependency_overrides[get_db] = lambda: _make_db_for_message_list([msg])

    response = TestClient(app).get(f"/api/chats/{chat.id}/messages")
    assert response.status_code == 200
    assert response.json()[0]["reasoning_steps"] is None


def test_list_messages_user_redacts_reasoning_steps() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    msg = _make_message_with_steps()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: _make_db_for_message_list([msg])

    response = TestClient(app).get(f"/api/chats/{chat.id}/messages")
    assert response.status_code == 200
    assert response.json()[0]["reasoning_steps"] is None


def test_create_message_feedback_persists_positive_rating() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    message = ChatMessage(
        id=uuid.uuid4(),
        chat_id=chat.id,
        role="assistant",
        content="answer",
    )
    message.created_at = datetime.now(UTC)
    db = _make_db_for_feedback(message)
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).post(
        f"/api/chats/{chat.id}/messages/{message.id}/feedback",
        json={"rating": "positive", "saved_time": "up_to_30_min", "comment": "Helpful"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["message_id"] == str(message.id)
    assert body["chat_id"] == str(chat.id)
    assert body["rating"] == "positive"
    assert body["saved_time"] == "up_to_30_min"
    assert body["comment"] == "Helpful"
    assert len(db.storage) == 1


def test_create_message_feedback_updates_existing_rating() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    message = ChatMessage(
        id=uuid.uuid4(),
        chat_id=chat.id,
        role="assistant",
        content="answer",
    )
    message.created_at = datetime.now(UTC)
    existing = _make_feedback(message, rating="positive")
    db = _make_db_for_feedback(message, existing)
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).post(
        f"/api/chats/{chat.id}/messages/{message.id}/feedback",
        json={"rating": "negative", "saved_time": "up_to_1h", "comment": "Wrong"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(existing.id)
    assert body["rating"] == "negative"
    assert body["saved_time"] is None
    assert body["comment"] == "Wrong"
    assert len(db.storage) == 1


def test_create_message_feedback_rejects_user_message() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    message = ChatMessage(
        id=uuid.uuid4(),
        chat_id=chat.id,
        role="user",
        content="question",
    )
    message.created_at = datetime.now(UTC)
    db = _make_db_for_feedback(message)
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).post(
        f"/api/chats/{chat.id}/messages/{message.id}/feedback",
        json={"rating": "positive", "saved_time": "up_to_15_min", "comment": "Nope"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Feedback can only be added to assistant messages"


def test_create_message_persists_langfuse_trace_id_for_assistant() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    db = _make_db_for_message_create()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).post(
        f"/api/chats/{chat.id}/messages",
        json={"role": "assistant", "content": "x", "langfuse_trace_id": "trace-123"},
    )

    assert response.status_code == 200
    assert response.json()["langfuse_trace_id"] == "trace-123"
    assert db.storage[0].langfuse_trace_id == "trace-123"


def test_create_message_ignores_langfuse_trace_id_for_user() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    db = _make_db_for_message_create()
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).post(
        f"/api/chats/{chat.id}/messages",
        json={"role": "user", "content": "x", "langfuse_trace_id": "trace-123"},
    )

    assert response.status_code == 200
    assert response.json()["langfuse_trace_id"] is None
    assert db.storage[0].langfuse_trace_id is None


def test_create_message_feedback_sends_langfuse_score_when_trace_present() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    message = ChatMessage(
        id=uuid.uuid4(),
        chat_id=chat.id,
        role="assistant",
        content="hi",
        langfuse_trace_id="trace-xyz",
    )
    message.created_at = datetime.now(UTC)
    db = _make_db_for_feedback(message)
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    with patch("src.api.routes.chats.score_user_feedback") as score:
        response = TestClient(app).post(
            f"/api/chats/{chat.id}/messages/{message.id}/feedback",
            json={"rating": "negative", "comment": "Wrong"},
        )

    assert response.status_code == 200
    score.assert_called_once()
    assert score.call_args.kwargs["trace_id"] == "trace-xyz"
    assert score.call_args.kwargs["rating"] == "negative"
    assert score.call_args.kwargs["comment"] == "Wrong"
    assert score.call_args.kwargs["metadata"] == {
        "chat_id": str(chat.id),
        "message_id": str(message.id),
    }
    assert score.call_args.kwargs["score_id"] == f"user_feedback-{message.id}"


def test_create_message_feedback_skips_langfuse_score_without_trace() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    message = ChatMessage(
        id=uuid.uuid4(),
        chat_id=chat.id,
        role="assistant",
        content="hi",
    )
    message.created_at = datetime.now(UTC)
    db = _make_db_for_feedback(message)
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: db

    with patch("src.api.routes.chats.score_user_feedback") as score:
        response = TestClient(app).post(
            f"/api/chats/{chat.id}/messages/{message.id}/feedback",
            json={"rating": "positive", "saved_time": "up_to_30_min"},
        )

    assert response.status_code == 200
    score.assert_not_called()


def test_list_messages_includes_current_user_feedback() -> None:
    app = _build_chats_app()
    chat = _make_chat()
    msg = _make_message_with_steps()
    msg.chat_id = chat.id
    feedback = _make_feedback(msg, rating="positive")
    app.dependency_overrides[get_user_chat] = lambda: chat
    app.dependency_overrides[get_current_user] = lambda: _FakeUser(FAKE_USER_ID, role="user")
    app.dependency_overrides[get_db] = lambda: _make_db_for_message_list([msg], [feedback])

    response = TestClient(app).get(f"/api/chats/{chat.id}/messages")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["feedback"]["id"] == str(feedback.id)
    assert body[0]["feedback"]["rating"] == "positive"
    assert body[0]["feedback"]["saved_time"] == "up_to_30_min"


def test_redact_event_super_admin_passes_through() -> None:
    event = {"type": "tool", "data": {"name": "t", "duration_ms": 5, "result": {"x": 1}}}
    assert _redact_event(event, is_super=True) == event


def test_redact_event_non_super_strips_status_and_tool_payload() -> None:
    status = {
        "type": "status",
        "data": {"message": "go", "step": 1, "tool_id": "x", "arguments": {"y": 1}},
    }
    tool = {
        "type": "tool",
        "data": {"name": "t", "duration_ms": 5, "result": {"x": 1}, "tool_id": "x"},
    }
    assert _redact_event(status, is_super=False) == {
        "type": "status",
        "data": {"message": "go", "step": 1},
    }
    assert _redact_event(tool, is_super=False) == {
        "type": "tool",
        "data": {"name": "t", "duration_ms": 5},
    }


def test_redact_event_non_super_passes_through_complete_and_error() -> None:
    complete = {"type": "complete", "data": {"content": "ok"}}
    error = {"type": "error", "data": {"message": "boom"}}
    assert _redact_event(complete, is_super=False) == complete
    assert _redact_event(error, is_super=False) == error
