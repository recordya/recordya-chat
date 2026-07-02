"""Langfuse client singleton for LLM observability (v3 API)."""

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generator

from src.core.config import settings

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

_langfuse: "Langfuse | None" = None
_langfuse_disabled: bool = False


def get_langfuse() -> "Langfuse | None":
    """Get Langfuse client singleton.
    
    Returns None if Langfuse is not enabled, not configured, or failed to initialize.
    """
    global _langfuse, _langfuse_disabled
    
    if _langfuse_disabled:
        return None
    
    if not settings.LANGFUSE_ENABLED:
        return None
    
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.warning("Langfuse enabled but keys not configured")
        return None
    
    if _langfuse is None:
        try:
            from langfuse import Langfuse
            
            client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
                environment=settings.ENV,
            )
            
            _langfuse = client
            logger.info(f"Langfuse client initialized (host={settings.LANGFUSE_HOST})")
            
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse: {e}")
            _langfuse_disabled = True
            return None
    
    return _langfuse


@contextmanager
def trace_span(
    name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Context manager for creating a Langfuse span (trace).
    
    Usage:
        with trace_span("agent_run", session_id=chat_id) as span:
            # do work
            span.update(output={"result": "..."})
    
    Yields None if Langfuse is not available.
    """
    langfuse = get_langfuse()
    if langfuse is None:
        yield None
        return
    
    try:
        span = langfuse.start_span(
            name=name,
            session_id=session_id,
            user_id=user_id,
            input=input,
            metadata=metadata,
        )
        try:
            yield span
        finally:
            span.end()
    except Exception as e:
        logger.warning(f"Langfuse span error: {e}")
        yield None


def score_user_feedback(
    trace_id: str,
    rating: str,
    *,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
    score_id: str | None = None,
) -> None:
    """Best-effort send of a ``user_feedback`` score to a Langfuse trace.

    ``positive`` maps to ``1`` and ``negative`` to ``0``. Passing a stable
    ``score_id`` upserts the same score, so editing feedback overwrites it
    instead of appending a duplicate. Failures are logged and swallowed so
    feedback persistence is never blocked by Langfuse.
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return

    try:
        langfuse.create_score(
            name="user_feedback",
            value=1 if rating == "positive" else 0,
            trace_id=trace_id,
            score_id=score_id,
            data_type="NUMERIC",
            comment=comment,
            metadata=metadata,
        )
    except Exception as e:
        logger.warning(f"Failed to send user_feedback score to Langfuse: {e}")


def shutdown_langfuse() -> None:
    """Shutdown Langfuse client and flush pending traces."""
    global _langfuse, _langfuse_disabled
    
    if _langfuse is not None:
        try:
            _langfuse.flush()
            logger.info("Langfuse flushed")
        except Exception as e:
            logger.warning(f"Error flushing Langfuse: {e}")
        _langfuse = None
    
    _langfuse_disabled = False
