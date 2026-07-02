from __future__ import annotations

import importlib
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

from src.core.config import Settings


def test_get_langfuse_passes_env_as_native_environment(monkeypatch) -> None:
    from src.core import langfuse as langfuse_module

    created_kwargs: dict[str, Any] = {}

    class FakeLangfuse:
        def __init__(self, **kwargs: Any) -> None:
            created_kwargs.update(kwargs)

    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=FakeLangfuse))
    monkeypatch.setattr(
        langfuse_module,
        "settings",
        Settings(
            LANGFUSE_ENABLED=True,
            LANGFUSE_PUBLIC_KEY="pk-test",
            LANGFUSE_SECRET_KEY="sk-test",
            ENV="staging",
        ),
    )
    monkeypatch.setattr(langfuse_module, "_langfuse", None)
    monkeypatch.setattr(langfuse_module, "_langfuse_disabled", False)

    langfuse_module.get_langfuse()

    assert created_kwargs["environment"] == "staging"


def test_observability_provider_passes_native_environment(monkeypatch) -> None:
    provider_module = importlib.import_module("src.services.providers.langfuse_provider")
    created_kwargs: dict[str, Any] = {}

    class FakeLangfuse:
        def __init__(self, **kwargs: Any) -> None:
            created_kwargs.update(kwargs)

    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=FakeLangfuse))

    provider_module.LangfuseObservabilityProvider(
        public_key="pk-test",
        secret_key="sk-test",
        environment="staging",
    )

    assert created_kwargs["environment"] == "staging"


def test_langfuse_run_keeps_environment_in_metadata(monkeypatch) -> None:
    agent_module = importlib.import_module("src.services.agent")

    captured_observation: dict[str, Any] = {}

    class FakeSpan:
        id = "span-test"
        trace_id = "trace-test"

        def update(self, **kwargs: Any) -> None:
            return None

        def end(self) -> None:
            return None

    class FakeObservationContext:
        def __enter__(self) -> FakeSpan:
            return FakeSpan()

        def __exit__(self, *args: Any) -> None:
            return None

    class FakeLangfuse:
        def start_as_current_observation(self, **kwargs: Any) -> FakeObservationContext:
            captured_observation.update(kwargs)
            return FakeObservationContext()

        def flush(self) -> None:
            return None

    class FakePlugin:
        name = "test_plugin"
        source_type = "sql"

    monkeypatch.setattr(agent_module, "get_langfuse", lambda: FakeLangfuse())
    monkeypatch.setattr(agent_module, "propagate_attributes", lambda **kwargs: nullcontext())
    monkeypatch.setattr(agent_module, "settings", Settings(ENV="production"))

    langfuse_run = agent_module._LangfuseRun(
        FakePlugin(),
        "gpt-test",
        "Question?",
        user_id="user-test",
        session_id="session-test",
    )
    assert langfuse_run.trace_id == "trace-test"

    langfuse_run.finish()

    assert captured_observation["metadata"]["environment"] == "production"


def test_score_user_feedback_maps_rating_to_numeric_value(monkeypatch) -> None:
    from src.core import langfuse as langfuse_module

    captured: list[dict[str, Any]] = []

    class FakeLangfuse:
        def create_score(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(langfuse_module, "get_langfuse", lambda: FakeLangfuse())

    langfuse_module.score_user_feedback("trace-1", "positive", comment="Nice")
    langfuse_module.score_user_feedback("trace-2", "negative")

    assert captured[0]["name"] == "user_feedback"
    assert captured[0]["value"] == 1
    assert captured[0]["trace_id"] == "trace-1"
    assert captured[0]["comment"] == "Nice"
    assert captured[0]["data_type"] == "NUMERIC"
    assert captured[1]["value"] == 0
    assert captured[1]["trace_id"] == "trace-2"
    assert captured[1]["data_type"] == "NUMERIC"


def test_score_user_feedback_forwards_metadata(monkeypatch) -> None:
    from src.core import langfuse as langfuse_module

    captured: list[dict[str, Any]] = []

    class FakeLangfuse:
        def create_score(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(langfuse_module, "get_langfuse", lambda: FakeLangfuse())

    metadata = {"chat_id": "chat-1", "message_id": "msg-1"}
    langfuse_module.score_user_feedback(
        "trace-1",
        "positive",
        comment="Nice",
        metadata=metadata,
        score_id="user_feedback-msg-1",
    )

    assert captured[0]["metadata"] == metadata
    assert captured[0]["score_id"] == "user_feedback-msg-1"


def test_score_user_feedback_noop_when_disabled(monkeypatch) -> None:
    from src.core import langfuse as langfuse_module

    monkeypatch.setattr(langfuse_module, "get_langfuse", lambda: None)

    langfuse_module.score_user_feedback("trace-1", "positive")


def test_score_user_feedback_swallows_client_errors(monkeypatch) -> None:
    from src.core import langfuse as langfuse_module

    class FakeLangfuse:
        def create_score(self, **kwargs: Any) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(langfuse_module, "get_langfuse", lambda: FakeLangfuse())

    langfuse_module.score_user_feedback("trace-1", "negative")
