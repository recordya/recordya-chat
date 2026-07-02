"""Chat management endpoints."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import delete, select

from src.api.dependencies import CurrentUser, DBSession, UserChat
from src.core.exceptions import bad_request, not_found
from src.core.langfuse import score_user_feedback
from src.core.roles import is_super_admin
from src.db.models import Chat, ChatMessage, ChatMessageFeedback

router = APIRouter()


class ChatResponse(BaseModel):
    """Chat response."""
    id: str
    title: str | None
    datasource: str | None = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ChatMessageFeedbackResponse(BaseModel):
    """Message feedback response."""
    id: str
    message_id: str
    chat_id: str
    rating: Literal["positive", "negative"]
    saved_time: str | None = None
    comment: str | None = None
    created_at: str
    updated_at: str


class ChatMessageResponse(BaseModel):
    """Chat message response."""
    id: str
    role: str
    content: str
    sql_query: str | None
    results_json: str | None
    tool_results: list[dict[str, Any]] | None = None
    reasoning_steps: list[dict[str, Any]] | None = None
    langfuse_trace_id: str | None = None
    feedback: ChatMessageFeedbackResponse | None = None
    created_at: str

    class Config:
        from_attributes = True


class CreateChatRequest(BaseModel):
    """Create chat request."""
    title: str = "Nowy czat"
    datasource: str | None = None


class UpdateChatRequest(BaseModel):
    """Update chat request."""
    title: str


class CreateMessageRequest(BaseModel):
    """Create message request."""
    role: str
    content: str
    sql_query: str | None = None
    results_json: str | None = None
    tool_results: list[dict[str, Any]] | None = None
    reasoning_steps: list[dict[str, Any]] | None = None
    langfuse_trace_id: str | None = None


class ChatMessageFeedbackRequest(BaseModel):
    """Create or update message feedback request."""
    rating: Literal["positive", "negative"]
    saved_time: str | None = None
    comment: str | None = None


def _feedback_to_response(feedback: ChatMessageFeedback) -> ChatMessageFeedbackResponse:
    return ChatMessageFeedbackResponse(
        id=str(feedback.id),
        message_id=str(feedback.message_id),
        chat_id=str(feedback.chat_id),
        rating=feedback.rating,  # type: ignore[arg-type]
        saved_time=feedback.saved_time,
        comment=feedback.comment,
        created_at=feedback.created_at.isoformat(),
        updated_at=feedback.updated_at.isoformat(),
    )


def _to_response(chat: Chat) -> ChatResponse:
    return ChatResponse(
        id=str(chat.id),
        title=chat.title,
        datasource=chat.datasource,
        created_at=chat.created_at.isoformat(),
        updated_at=chat.updated_at.isoformat(),
    )


def _message_to_response(
    message: ChatMessage,
    *,
    reasoning_steps: list[dict[str, Any]] | None,
    feedback: ChatMessageFeedback | None = None,
) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=str(message.id),
        role=message.role,
        content=message.content,
        sql_query=message.sql_query,
        results_json=message.results_json,
        tool_results=message.tool_results,
        reasoning_steps=reasoning_steps,
        langfuse_trace_id=message.langfuse_trace_id,
        feedback=_feedback_to_response(feedback) if feedback else None,
        created_at=message.created_at.isoformat(),
    )


@router.get("/chats", response_model=list[ChatResponse])
async def list_chats(
    current_user: CurrentUser,
    db: DBSession,
) -> list[ChatResponse]:
    """List all chats for current user."""
    result = await db.execute(
        select(Chat)
        .where(Chat.user_id == current_user.id)
        .order_by(Chat.updated_at.desc())
    )
    chats = result.scalars().all()

    return [_to_response(chat) for chat in chats]


@router.post("/chats", response_model=ChatResponse)
async def create_chat(
    request: CreateChatRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> ChatResponse:
    """Create a new chat."""
    chat = Chat(
        user_id=current_user.id,
        title=request.title,
        datasource=request.datasource,
    )
    db.add(chat)
    await db.flush()
    await db.refresh(chat)

    return _to_response(chat)


@router.get("/chats/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat: UserChat,
) -> ChatResponse:
    """Get a specific chat."""
    return _to_response(chat)


@router.patch("/chats/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat: UserChat,
    request: UpdateChatRequest,
    db: DBSession,
) -> ChatResponse:
    """Update a chat."""
    chat.title = request.title
    await db.flush()
    await db.refresh(chat)

    return _to_response(chat)


@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat: UserChat,
    db: DBSession,
) -> dict:
    """Delete a chat and all its messages."""
    await db.delete(chat)
    return {"success": True}


@router.get("/chats/{chat_id}/messages", response_model=list[ChatMessageResponse])
async def list_messages(
    chat: UserChat,
    current_user: CurrentUser,
    db: DBSession,
) -> list[ChatMessageResponse]:
    """List all messages in a chat."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.chat_id == chat.id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()

    feedback_by_message_id: dict[Any, ChatMessageFeedback] = {}
    message_ids = [msg.id for msg in messages]
    if message_ids:
        feedback_result = await db.execute(
            select(ChatMessageFeedback).where(
                ChatMessageFeedback.user_id == current_user.id,
                ChatMessageFeedback.message_id.in_(message_ids),
            )
        )
        feedback_by_message_id = {
            feedback.message_id: feedback
            for feedback in feedback_result.scalars().all()
        }

    is_super = is_super_admin(current_user.role)
    return [
        _message_to_response(
            msg,
            reasoning_steps=msg.reasoning_steps if is_super else None,
            feedback=feedback_by_message_id.get(msg.id),
        )
        for msg in messages
    ]


@router.post("/chats/{chat_id}/messages", response_model=ChatMessageResponse)
async def create_message(
    chat: UserChat,
    request: CreateMessageRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> ChatMessageResponse:
    """Create a new message in a chat."""
    is_super = is_super_admin(current_user.role)
    reasoning_steps = request.reasoning_steps if is_super else None
    langfuse_trace_id = (
        request.langfuse_trace_id if request.role == "assistant" else None
    )
    message = ChatMessage(
        chat_id=chat.id,
        role=request.role,
        content=request.content,
        sql_query=request.sql_query,
        results_json=request.results_json,
        tool_results=request.tool_results,
        reasoning_steps=reasoning_steps,
        langfuse_trace_id=langfuse_trace_id,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)

    return _message_to_response(
        message,
        reasoning_steps=message.reasoning_steps,
    )


@router.post(
    "/chats/{chat_id}/messages/{message_id}/feedback",
    response_model=ChatMessageFeedbackResponse,
)
async def create_message_feedback(
    chat: UserChat,
    message_id: uuid.UUID,
    request: ChatMessageFeedbackRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> ChatMessageFeedbackResponse:
    """Create or update feedback for an assistant message."""
    message_result = await db.execute(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.chat_id == chat.id,
        )
    )
    message = message_result.scalar_one_or_none()
    if not message:
        raise not_found("Message not found")
    if message.role != "assistant":
        raise bad_request("Feedback can only be added to assistant messages")

    feedback_result = await db.execute(
        select(ChatMessageFeedback).where(
            ChatMessageFeedback.user_id == current_user.id,
            ChatMessageFeedback.message_id == message.id,
        )
    )
    feedback = feedback_result.scalar_one_or_none()
    if feedback is None:
        feedback = ChatMessageFeedback(
            message_id=message.id,
            chat_id=chat.id,
            user_id=current_user.id,
            rating=request.rating,
            saved_time=request.saved_time if request.rating == "positive" else None,
            comment=request.comment,
        )
        db.add(feedback)
    else:
        feedback.rating = request.rating
        feedback.saved_time = request.saved_time if request.rating == "positive" else None
        feedback.comment = request.comment

    await db.flush()
    await db.refresh(feedback)

    if message.langfuse_trace_id:
        score_user_feedback(
            trace_id=message.langfuse_trace_id,
            rating=feedback.rating,
            comment=feedback.comment,
            metadata={
                "chat_id": str(chat.id),
                "message_id": str(message.id),
            },
            score_id=f"user_feedback-{message.id}",
        )

    return _feedback_to_response(feedback)


@router.delete("/chats/{chat_id}/messages/latest")
async def delete_latest_messages(
    chat: UserChat,
    db: DBSession,
    count: int = Query(default=2, ge=1, le=10),
) -> dict:
    """Delete the last *count* messages from a chat (by created_at DESC)."""
    # Find IDs of the latest N messages
    subquery = (
        select(ChatMessage.id)
        .where(ChatMessage.chat_id == chat.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(count)
    )
    await db.execute(
        delete(ChatMessage).where(ChatMessage.id.in_(subquery))
    )
    return {"deleted": count}


@router.get("/chats/search/{query}")
async def search_chats(
    query: str,
    current_user: CurrentUser,
    db: DBSession,
) -> list[ChatResponse]:
    """Search chats by title."""
    result = await db.execute(
        select(Chat)
        .where(
            Chat.user_id == current_user.id,
            Chat.title.ilike(f"%{query}%")
        )
        .order_by(Chat.updated_at.desc())
    )
    chats = result.scalars().all()

    return [_to_response(chat) for chat in chats]
