# recordya-chat

An extensible chatbot UI platform with a pluggable architecture. The core application provides a complete chat interface — authentication, conversation management, streaming responses — while remaining fully agnostic to the domain. All domain knowledge, tools, and custom UI live in **plugins**.

## Key Features

- **Chat UI out of the box** — responsive React interface with streaming SSE responses, chat history, and user authentication
- **Response feedback** — persisted thumbs-up/down feedback for assistant messages, with optional saved-time and comment metadata
- **Plugin system** — extend both backend logic (LLM tools, data sources, agents) and frontend UI (custom widgets, views, slots) without modifying the core
- **OpenAI-compatible** — works with any LLM provider that exposes an OpenAI-compatible API (OpenRouter, Fireworks, local models via Ollama, etc.)
- **Observability** — built-in Langfuse integration for LLM tracing (optional)

## Quick Start

### Recommended: use as a git submodule

`recordya-chat` is designed to be used as a **git submodule** inside your own project, with plugins living in a sibling directory:

```bash
# 1. Create your project
mkdir my-project && cd my-project
git init

# 2. Add recordya-chat as a submodule
git submodule add <core-repo-url> core
git submodule update --init

# 3. Create your plugins directory
mkdir -p plugins/my_plugin/backend
mkdir -p plugins/my_plugin/frontend

# 4. Configure
cp core/.env.example core/.env    # add your OPENAI_API_KEY
```

Your project structure should look like:

```
my-project/
├── core/              # recordya-chat (git submodule)
│   ├── backend/
│   ├── frontend/
│   ├── docker-compose.yml
│   └── ...
└── plugins/           # your plugins (sibling to core/)
    └── my_plugin/
        ├── backend/
        └── frontend/
```

### Docker (recommended)

```bash
cd core
cp .env.example .env          # add your OPENAI_API_KEY

# Start all services (first run also copies .env and seeds the default user)
make setup                    # default Keycloak mode runs `docker compose --profile sso up -d`

# Default login (after ~30 seconds)
# Keycloak mode (default): admin@test.com / admin123 — user seeded from realm-export.json
# Local mode: ./scripts/create-user.sh
```

> **Note:** `docker-compose.yml` mounts the sibling `../plugins` directory (next to `core/`) to `/plugins` in the containers. Plugins are optional — the app starts normally with an empty or missing plugins directory, so a fresh clone runs out of the box with zero plugins.

Docker Compose also starts **Mailpit**, a local email sink for transactional
emails from the backend and Keycloak. Open http://localhost:8025 to inspect
captured messages. SMTP is exposed on host port `1025` and as `mailpit:1025`
inside the Docker network. See [Email Service](docs/services/email.md) for
details and port-conflict notes.

### Manual (without Docker)

Requires Python 3.12+, Node.js 18+, and PostgreSQL 15+.

```bash
# Configure (from the core/ directory)
cd core
cp .env.example .env          # add your OPENAI_API_KEY

# Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn src.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev                   # http://localhost:8080
```

### Access

| Service | URL |
|---------|-----|
| Frontend | http://localhost:8080 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Keycloak Admin | http://localhost:8180/admin (`admin` / `admin`) |
| Mailpit | http://localhost:8025 |
| Login | `admin@test.com` / `admin123` |

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Frontend | React 18 · TypeScript · Vite · Tailwind · shadcn/ui |
| Backend | Python 3.12 · FastAPI (async) · SQLAlchemy · asyncpg |
| Database | PostgreSQL (app DB + plugin DBs) |
| AI | OpenAI-compatible API via LlmFacade |
| Auth | Keycloak SSO (OIDC) · JWT · bcrypt (local fallback) |

## Project Structure

```
my-project/
├── core/                # recordya-chat (this repo, used as git submodule)
│   ├── frontend/        # React app (Vite)
│   ├── backend/         # Python API (FastAPI)
│   ├── keycloak/        # Keycloak SSO config (realm seed, login theme)
│   ├── docs/            # Architecture & plugin development docs
│   └── CONTRIBUTING.md  # Development guidelines and conventions
└── plugins/             # Your plugin implementations (external to core)
    └── my_plugin/
        ├── backend/     # Plugin backend (plugin.py, schema.py, tools.py, manifest.yaml)
        └── frontend/    # Plugin frontend (index.ts, components/)
```

> **Plugins live outside core.** Both the backend and the frontend resolve plugins from the sibling `plugins/` directory (next to `core/`) — the same location in Docker Compose (mounted to `/plugins`) and in manual (non-Docker) runs. The application starts normally when no plugins are present.

## Authentication

The platform supports two authentication modes controlled by `AUTH_MODE` in `.env`:

| Mode | `AUTH_MODE` | Description |
|------|-------------|-------------|
| **Keycloak (SSO)** | `keycloak` | OpenID Connect via Keycloak. Users managed in Keycloak, auto-provisioned in app DB. **Default.** |
| **Local** | `local` | Email + password stored in app DB. No external IdP. |

To switch: set `AUTH_MODE` in `.env` and restart backend. No code changes needed.

See [Authentication Guide](docs/authentication.md) for full details (user management, role mapping, environment variables).

## Configuration

All configuration lives in a single root `.env` file (copy from `.env.example`).

### LLM Providers

Any OpenAI-compatible API works. Set in `.env`:

```bash
# OpenAI (default)
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
DEFAULT_LLM_MODEL=gpt-5.2

# Fireworks AI
OPENAI_BASE_URL=https://api.fireworks.ai/inference/v1
OPENAI_API_KEY=fw_...
DEFAULT_LLM_MODEL=accounts/fireworks/models/llama-v3p1-70b-instruct

# Local models (Ollama)
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
DEFAULT_LLM_MODEL=llama2
```

### Localization

The UI language is **static and config-driven** by a single setting:

```bash
DEFAULT_LOCALE=en        # en (default) | pl
```

`DEFAULT_LOCALE` is the single source of truth for the displayed language
across the **frontend**, **backend messages**, and **Keycloak** (login screen
and transactional emails). The backend exposes it via `GET /auth/config`; the
frontend initializes i18next with it once at startup. There is no runtime
language switching and no browser detection — unset or unknown values fall back
to `en`. See the [i18n guide](docs/i18n.md) for details.

## Extending with Plugins

Plugins can add backend logic **and** frontend UI. The core never needs to change.

```
BasePlugin (ABC)
├── ExecutablePlugin       <- full control: run() yields events
├── ManagedPlugin          <- service-managed tool loop
│   └── BaseSQLPlugin      <- PostgreSQL convenience base
└── ViewPlugin             <- custom UI view (not a chat agent)
```

See the [Plugin Development Guide](docs/plugin-development.md) for a full walkthrough.

## Commands

### Docker

```bash
make setup              # Initial setup (copy .env, start services, create user)
make up                 # Start all services
make down               # Stop all services
make restart            # Restart all services
make logs               # View logs (all services)
make build              # Rebuild images
make clean              # Remove containers, volumes, images
```

### Testing (Docker — requires `make up`)

```bash
make test               # Run all tests (backend + frontend)
make test-backend       # Run backend tests (pytest)
make test-frontend      # Run frontend tests (vitest)
```

### Local Development

```bash
make dev-backend        # Start backend with hot reload (requires .venv)
make dev-frontend       # Start frontend dev server (requires npm install)
make dev-test           # Run all tests locally
```

### Database

```bash
make db-shell           # Connect to PostgreSQL
make db-backup          # Backup to backups/ directory
make db-restore FILE=backups/backup.sql
```

## API Quick Reference

```bash
# Authenticate (local mode)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@test.com", "password": "admin123"}' \
  | jq -r '.access_token')

# In Keycloak mode, tokens are obtained via OIDC flow in the browser.
# See docs/authentication.md for details.

# List agent plugins (data sources)
curl http://localhost:8000/api/datasources \
  -H "Authorization: Bearer $TOKEN"

# List view plugins (navigation rail)
curl http://localhost:8000/api/views \
  -H "Authorization: Bearer $TOKEN"

# Chat (streaming SSE)
curl -N http://localhost:8000/api/agent/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello!", "datasource": "your_plugin"}'

# Save feedback for an assistant message
curl -X POST http://localhost:8000/api/chats/$CHAT_ID/messages/$MESSAGE_ID/feedback \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"rating": "positive", "saved_time": "do 30 min", "comment": "Helpful"}'

# Create user via API (local mode only)
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepassword123"}'
```

Full API docs: http://localhost:8000/docs (Swagger UI)

## Troubleshooting

### Port already in use

```bash
lsof -i :8080              # check what's using the port
brew services stop postgresql  # stop local PostgreSQL (macOS)
```

Or change port mapping in `docker-compose.yml`.

### Services not starting / keep restarting

```bash
docker compose ps          # check status
docker compose logs -f     # view logs
```

Common causes: missing `OPENAI_API_KEY` in `.env`, database not ready (wait 30s), port conflicts.

### Frontend shows white page

```bash
docker compose down
docker volume rm recordya-chat_frontend_node_modules
docker compose up -d --build frontend
```

### Nuclear reset (deletes all data)

```bash
docker compose down -v
docker compose up -d
# Keycloak mode: seed user (admin@test.com) is auto-imported from realm-export.json
# Local mode: sleep 30 && ./scripts/create-user.sh
```

## Production Checklist

Before deploying to production:

1. Change `SECRET_KEY` in `.env` to a strong random value
2. Use strong database passwords (including `KEYCLOAK_DB_PASSWORD`)
3. Change Keycloak admin credentials (`KEYCLOAK_ADMIN_PASSWORD`)
4. Remove or disable the **development-only** seed user `admin@test.com` / `admin123` in `keycloak/realm-export.json` (it is imported only on first start)
5. Configure HTTPS/SSL (including Keycloak — update `KEYCLOAK_FRONTEND_URL`)
6. Restrict `CORS_ORIGINS` to your domain
7. Set `DEBUG=false`
8. Set up database backups
9. Consider Docker secrets for sensitive values

## Documentation

- [Authentication](docs/authentication.md) — auth modes (Keycloak SSO / local), switching, user management, role mapping
- [System Architecture](docs/architecture.md) — modules, data flow, API endpoints, environment variables
- [Plugin Development](docs/plugin-development.md) — creating backend & frontend plugins, SDK reference
- [Internationalization (i18n)](docs/i18n.md) — config-driven locale, translation bundles, conventions
- [Prompt Testing & Evaluation](docs/prompt-testing.md) — structural tests, Langfuse evals, regression detection, staging→production workflow
- [Streaming Protocol](docs/streaming.md) — SSE streaming protocol (event types, token streaming)
- [Email Service](docs/services/email.md) — SMTP configuration and the `send_email()` helper
- [Contributing Guide](CONTRIBUTING.md) — development guidelines and conventions
- Swagger UI: http://localhost:8000/docs (when backend is running)

## License

This project is licensed under the [MIT License](LICENSE).
