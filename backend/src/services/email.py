"""SMTP delivery service for plaintext email.

Reads SMTP configuration from environment variables so the same code path
works against MailPit locally (no auth, plaintext) and any SMTP relay or
transactional email provider in production (auth + STARTTLS).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    use_tls: bool
    sender: str

    @classmethod
    def from_env(cls) -> SmtpConfig | None:
        host = os.getenv("SMTP_HOST")
        sender = os.getenv("SMTP_FROM")
        if not host or not sender:
            return None
        port_raw = os.getenv("SMTP_PORT", "1025")
        try:
            port = int(port_raw)
        except ValueError:
            logger.error("Invalid SMTP_PORT value: %s", port_raw)
            return None
        username = os.getenv("SMTP_USERNAME") or None
        password = os.getenv("SMTP_PASSWORD") or None
        use_tls = os.getenv("SMTP_USE_TLS", "false").strip().lower() in {"1", "true", "yes"}
        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_tls,
            sender=sender,
        )


def build_message(*, sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


async def send_email(
    *,
    recipient: str,
    subject: str,
    body: str,
    config: SmtpConfig | None = None,
) -> bool:
    """Deliver a plaintext email via SMTP.

    Returns ``True`` on successful handover to the SMTP server, ``False``
    if configuration is missing or the SMTP transaction failed.
    """
    cfg = config or SmtpConfig.from_env()
    if cfg is None:
        logger.error("SMTP not configured (SMTP_HOST/SMTP_FROM missing) — email NOT sent")
        return False

    message = build_message(
        sender=cfg.sender,
        recipient=recipient,
        subject=subject,
        body=body,
    )
    try:
        await aiosmtplib.send(
            message,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.username,
            password=cfg.password,
            start_tls=cfg.use_tls,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        logger.error("SMTP delivery failed: %s", exc)
        return False
    logger.info("Email delivered to %s via %s:%s", recipient, cfg.host, cfg.port)
    return True
