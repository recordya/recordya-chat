"""Unit tests for the SMTP email service."""

from __future__ import annotations

from unittest.mock import AsyncMock

import aiosmtplib
import pytest

from src.services import email as email_service
from src.services.email import SmtpConfig, build_message, send_email


@pytest.fixture
def cfg() -> SmtpConfig:
    return SmtpConfig(
        host="localhost",
        port=1025,
        username=None,
        password=None,
        use_tls=False,
        sender="Service <noreply@localhost>",
    )


class TestSmtpConfigFromEnv:
    def test_returns_none_when_host_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setenv("SMTP_FROM", "x@y")
        assert SmtpConfig.from_env() is None

    def test_returns_none_when_sender_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "localhost")
        monkeypatch.delenv("SMTP_FROM", raising=False)
        assert SmtpConfig.from_env() is None

    def test_parses_full_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "u")
        monkeypatch.setenv("SMTP_PASSWORD", "p")
        monkeypatch.setenv("SMTP_USE_TLS", "true")
        monkeypatch.setenv("SMTP_FROM", "from@x")
        cfg = SmtpConfig.from_env()
        assert cfg is not None
        assert cfg.host == "smtp.example.com"
        assert cfg.port == 587
        assert cfg.username == "u"
        assert cfg.password == "p"
        assert cfg.use_tls is True
        assert cfg.sender == "from@x"

    def test_invalid_port_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "h")
        monkeypatch.setenv("SMTP_FROM", "f")
        monkeypatch.setenv("SMTP_PORT", "not-a-number")
        assert SmtpConfig.from_env() is None

    def test_default_port_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "h")
        monkeypatch.setenv("SMTP_FROM", "f")
        monkeypatch.delenv("SMTP_PORT", raising=False)
        cfg = SmtpConfig.from_env()
        assert cfg is not None
        assert cfg.port == 1025

    def test_empty_credentials_become_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMTP_HOST", "h")
        monkeypatch.setenv("SMTP_FROM", "f")
        monkeypatch.setenv("SMTP_USERNAME", "")
        monkeypatch.setenv("SMTP_PASSWORD", "")
        cfg = SmtpConfig.from_env()
        assert cfg is not None
        assert cfg.username is None
        assert cfg.password is None


class TestBuildMessage:
    def test_message_headers_and_body(self) -> None:
        msg = build_message(
            sender="from@x",
            recipient="to@y",
            subject="Sub",
            body="Hello",
        )
        assert msg["From"] == "from@x"
        assert msg["To"] == "to@y"
        assert msg["Subject"] == "Sub"
        assert "Hello" in msg.get_content()


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_FROM", raising=False)
        ok = await send_email(recipient="x@y", subject="s", body="b", config=None)
        assert ok is False

    @pytest.mark.asyncio
    async def test_calls_aiosmtplib_with_config(
        self, monkeypatch: pytest.MonkeyPatch, cfg: SmtpConfig
    ) -> None:
        send_mock = AsyncMock()
        monkeypatch.setattr(email_service.aiosmtplib, "send", send_mock)
        ok = await send_email(recipient="x@y", subject="s", body="b", config=cfg)
        assert ok is True
        send_mock.assert_awaited_once()
        kwargs = send_mock.await_args.kwargs
        assert kwargs["hostname"] == cfg.host
        assert kwargs["port"] == cfg.port
        assert kwargs["start_tls"] is False

    @pytest.mark.asyncio
    async def test_returns_false_on_smtp_exception(
        self, monkeypatch: pytest.MonkeyPatch, cfg: SmtpConfig
    ) -> None:
        async def boom(*args, **kwargs):
            raise aiosmtplib.SMTPException("boom")

        monkeypatch.setattr(email_service.aiosmtplib, "send", boom)
        ok = await send_email(recipient="x@y", subject="s", body="b", config=cfg)
        assert ok is False

    @pytest.mark.asyncio
    async def test_returns_false_on_oserror(
        self, monkeypatch: pytest.MonkeyPatch, cfg: SmtpConfig
    ) -> None:
        async def boom(*args, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(email_service.aiosmtplib, "send", boom)
        ok = await send_email(recipient="x@y", subject="s", body="b", config=cfg)
        assert ok is False
