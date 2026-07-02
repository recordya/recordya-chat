# Email Service

Shared SMTP transport for outbound email. Lives in `src/services/email.py`
so any plugin or core component can deliver email without bundling its own
SMTP client.

The service handles **transport only**. Message content (subject, body,
templating, recipients) is the caller's responsibility — alerts, example_customer
notifications, password resets, signup confirmations, ad-hoc messages all
share the same code path.

## Capabilities and Limits

The current implementation supports:
- UTF-8 plaintext body
- Single `To:` recipient
- Single sender via `SMTP_FROM`
- STARTTLS upgrade (optional) and SMTP AUTH (optional)
- Async delivery via `aiosmtplib`

Not supported today (extend the service if you need them):
- HTML/multipart bodies
- Multiple recipients, CC, BCC
- Attachments, inline images
- Custom headers (Reply-To, List-Unsubscribe, etc.)
- Retry/backoff — delivery is best-effort, failures are logged and surfaced
  to the caller via the `False` return value

## Public API

```python
from src.services.email import SmtpConfig, send_email, build_message
```

| Symbol | Purpose |
|--------|---------|
| `SmtpConfig` | Frozen dataclass with `host`, `port`, `username`, `password`, `use_tls`, `sender` |
| `SmtpConfig.from_env()` | Build config from `SMTP_*` env vars; returns `None` if `SMTP_HOST` or `SMTP_FROM` is missing |
| `send_email(*, recipient, subject, body, config=None)` | Async; returns `True` on successful SMTP handover, `False` otherwise. If `config` is `None`, falls back to `SmtpConfig.from_env()` |
| `build_message(*, sender, recipient, subject, body)` | Build a `email.message.EmailMessage` with UTF-8 plaintext body. Used internally by `send_email`; exposed for tests and custom transports |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SMTP_HOST` | yes | — | SMTP server hostname (e.g. `smtp.gmail.com`, `localhost` for MailPit) |
| `SMTP_FROM` | yes | — | Sender address; supports RFC 5322 form `Name <addr@domain>` |
| `SMTP_PORT` | no | `1025` | SMTP port (587 for STARTTLS, 465 for SMTPS, 1025 for MailPit/MailHog) |
| `SMTP_USERNAME` | no | — | SMTP auth username; empty string treated as unset |
| `SMTP_PASSWORD` | no | — | SMTP auth password; empty string treated as unset |
| `SMTP_USE_TLS` | no | `false` | `true`/`1`/`yes` enables STARTTLS upgrade after connect |

If `SMTP_HOST` or `SMTP_FROM` is missing, `send_email()` returns `False` and
logs an error — it does **not** raise. Callers should degrade gracefully when
SMTP is not configured (e.g. local dev without MailPit running).

## Usage

```python
from src.services.email import SmtpConfig, send_email

ok = await send_email(
    recipient="ops@example.com",
    subject="Hello",
    body="Plaintext body.",
    config=SmtpConfig.from_env(),
)
if not ok:
    logger.error("Email NOT delivered")
```

For most callers, omitting `config=` and letting `send_email` read the env
itself is enough:

```python
ok = await send_email(recipient="...", subject="...", body="...")
```

## Local Development

Point `SMTP_HOST` at a local SMTP sink. [MailPit](https://github.com/axllent/mailpit)
is recommended (single binary, web UI on port 8025):

```bash
brew install mailpit
mailpit                       # ESMTP on :1025, UI on http://localhost:8025
```

Then in `.env`:
```
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_FROM=Recordya Local <noreply@localhost>
# SMTP_USERNAME, SMTP_PASSWORD, SMTP_USE_TLS left unset
```

### macOS Note

`aiosmtplib` calls `socket.getfqdn()` for the SMTP HELO/EHLO greeting. On
some macOS networks this can hang for several seconds. The production code
path on Linux (Cloud Run) is unaffected. For local smoke tests where this is
a problem, call `aiosmtplib.send(..., local_hostname='localhost')` directly
instead of `send_email()`.

## Docker Compose

The root `docker-compose.yml` ships a `mailpit` service that **always starts**
(no profile gate). It exposes SMTP on host port `1025` and a web UI on
`http://localhost:8025`. The backend container is wired to it via
`SMTP_HOST=mailpit` (Docker network DNS), so any `send_email()` call from
core or a plugin running inside the backend container lands in MailPit by
default.

```bash
cd core
docker compose up -d                  # mailpit + postgres + backend + frontend
open http://localhost:8025            # MailPit UI
```

**Port conflict:** if you already have a native MailPit or MailHog running on
the host (e.g. `brew install mailpit && mailpit`), the Docker container will
fail to bind `1025`/`8025`. Stop the native instance first
(`brew services stop mailpit`) or remap the host ports in your override file.

**Override SMTP target from `.env`:** all SMTP env vars except `SMTP_HOST`
honour `.env` values via `${VAR:-default}`. `SMTP_HOST` is hardcoded to
`mailpit` inside the backend container because that name only resolves
within the Docker network — overriding it from `.env` would break in-network
delivery. To target an external SMTP server from the backend container,
edit `docker-compose.yml` directly or use a compose override file.

## Production

Use the corporate SMTP relay or a transactional email provider's SMTP
endpoint:

```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=mailer@example.com
SMTP_PASSWORD=<from secret manager>
SMTP_USE_TLS=true
SMTP_FROM=Recordya <noreply@example.com>
```

Inject these via the deployment's secret manager (Cloud Run env vars sourced
from Secret Manager, K8s Secret, etc.) — never commit credentials.

## Testing

Mock `aiosmtplib.send` via `monkeypatch`:

```python
from unittest.mock import AsyncMock
from src.services import email as email_service

async def test_send_email(monkeypatch):
    send_mock = AsyncMock()
    monkeypatch.setattr(email_service.aiosmtplib, "send", send_mock)
    ...
    send_mock.assert_awaited_once()
```

For consumers that import `send_email` into their own module
(e.g. `from src.services.email import send_email` at module top-level),
patch the symbol on the consumer module instead:

```python
monkeypatch.setattr(my_module, "send_email", AsyncMock(return_value=True))
```

See `core/backend/tests/test_email_service.py` for the full test suite.
