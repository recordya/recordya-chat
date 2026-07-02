# Contributing

This repository is designed for extensibility. Contributors should leverage the plugin system and follow strict naming and coding conventions to keep the system consistent and safe to extend.

## Project Overview

**recordya-chat** is a generic intelligent assistant platform with a pluggable data source architecture. The main application is completely agnostic to the underlying data - all domain knowledge resides in plugins.

**Philosophy:**
```
PLUGIN = "CO robić" (strategy, orchestration, agents, UI)
CORE   = "JAK robić" (primitives, infrastructure, event bus)
```

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Frontend | React 18 + TypeScript + Vite + Tailwind + shadcn/ui |
| Backend | Python 3.12 + FastAPI (async) |
| Database | PostgreSQL (APP_DB for app data, plugin DBs for domain data) |
| AI | OpenAI-compatible API via LlmFacade |
| Observability | Langfuse (LLM tracing) |
| Auth | Keycloak SSO (OIDC) / local JWT + bcrypt |

## Repository Structure

`recordya-chat` (this repo) is designed to be used as a **git submodule** inside a parent project. Plugins live in a **sibling directory**, not inside core:

```
my-project/                          # Your project (parent repo)
├── core/                            # recordya-chat (git submodule)
│   ├── frontend/                    # React app (Vite)
│   │   └── src/
│   │       ├── components/          # Shared React components
│   │       │   └── ui/              # shadcn/ui primitives
│   │       ├── contexts/            # React contexts (ModelSettingsContext)
│   │       ├── hooks/               # Custom React hooks
│   │       ├── i18n/                # Frontend i18n (locales, setup)
│   │       ├── lib/                 # Utilities (api.ts, config.ts, utils.ts)
│   │       ├── pages/               # Route pages
│   │       ├── plugins/             # Frontend plugin SDK
│   │       └── utils/               # Shared helpers
│   ├── backend/                     # Python API (FastAPI)
│   │   ├── src/
│   │   │   ├── core/                # Config, protocols, engine, discovery, registry
│   │   │   ├── plugin_sdk/          # Stable SDK for plugin developers
│   │   │   │   └── evals/           # Shared eval framework (evaluators, LLMJudge, seeding, execution)
│   │   │   ├── services/            # AgentService, factory, observability
│   │   │   ├── datasources/         # Built-in data source integrations
│   │   │   ├── llm/                 # LLM facade / provider integration
│   │   │   ├── api/                 # FastAPI routes
│   │   │   └── db/                  # SQLAlchemy models, migrations
│   │   └── tests/                   # pytest tests
│   ├── keycloak/                    # Keycloak SSO configuration
│   │   ├── realm-export.json        # Realm seed (imported on first start)
│   │   └── themes/recordya/         # Custom login page theme
│   ├── docs/                        # Architecture and plugin development docs
│   │   ├── architecture.md          # System architecture
│   │   ├── authentication.md        # Auth modes (Keycloak SSO / local)
│   │   ├── i18n.md                  # Internationalization model
│   │   ├── plugin-development.md    # Plugin development guide
│   │   ├── prompt-testing.md        # Prompt testing & evaluation guide
│   │   ├── streaming.md             # SSE streaming protocol (event types, token streaming)
│   │   └── services/               # Service-specific docs
│   │       └── email.md             # Email service (SMTP transport)
│   ├── plugins/                     # Staged plugin packages for deployment builds (empty by default)
│   ├── scripts/                     # Helper scripts (create-user.sh, test-api.sh)
│   ├── docker-compose.yml           # Core services (backend, frontend, db, keycloak)
│   ├── Makefile                     # Dev/test shortcuts
│   ├── tsconfig.json                # TypeScript config
│   ├── README.md                    # Project readme
│   ├── LICENSE                      # License
│   └── CONTRIBUTING.md              # This file
│
└── plugins/                         # Plugin implementations (external to core)
    └── <plugin_name>/               # Example plugin
        ├── backend/                 # Plugin implementation
        │   ├── plugin.py            # Main plugin class
        │   ├── schema.py            # PROMPT_TEMPLATE
        │   ├── tools.py             # SQL_TOOLS list
        │   ├── manifest.yaml        # Plugin metadata
        │   ├── config.yaml          # Config with $VAR placeholders (committed)
        │   ├── .env                 # Secrets (gitignored)
        │   ├── .env.example         # Secrets template (committed)
        │   ├── tests/               # Unit tests (pytest, offline)
        │   └── evals/               # Behavioural evals (Langfuse, online)
        └── frontend/                # Custom UI components
            ├── index.ts             # Registration function
            └── components/          # Custom UI components
```

**Plugin discovery:** Both the backend and the frontend `@plugins` alias resolve plugins from the sibling `plugins/` directory (next to `core/`) — the same location in Docker Compose (mounted to `/plugins`) and in manual (non-Docker) runs. Deployment builds override this: the backend production image uses `/app/plugins`, and the CI frontend build uses a filtered `core/plugins` (which takes precedence whenever it contains staged plugin packages). The application starts normally when no plugins are present — the platform ships with zero plugins out of the box.

## Setup Commands

### Backend
```bash
cp .env.example .env       # Root-level .env — configure databases and API keys
cd backend
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
pip install -e ".[dev]"
alembic upgrade head       # Run migrations
uvicorn src.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev                # http://localhost:8080
```

Frontend uses runtime config via `frontend/public/config/config.json` (default API URL: `http://localhost:8000`). No `.env` file needed.

## Testing Instructions

### Backend Tests (pytest)
```bash
cd backend                                      # from repo root
source .venv/bin/activate
python -m pytest tests/ -v --tb=short           # Run all tests
python -m pytest tests/test_plugin_sdk.py -v    # Run specific test file
python -m pytest tests/ -k "test_name" -v       # Run tests matching pattern
python -m pytest tests/ --cov=src               # With coverage
```

### Frontend Tests (vitest)
```bash
cd frontend               # from repo root
npm run test              # Run all tests
npm run test:watch        # Watch mode
```

### All Tests via Make
```bash
# from repo root
make test                 # all tests (backend + frontend, in Docker; starts deps automatically)
make test-backend         # pytest (Docker)
make test-frontend        # vitest (Docker)
make dev-test             # all tests locally (requires .venv + npm install)
```

### Before Committing
- All tests must pass
- Run `ruff check .` for Python linting (in `backend/`)
- Run `npm run lint` for TypeScript linting (in `frontend/`)

### Prompt Tests — Hands Off
- **NEVER** update prompt snapshot tests (e.g. `TestMyPluginPromptSnapshot`, `EXPECTED_HASH`) without explicit developer approval.
- **NEVER** modify `expected_output`, `expected_behaviour`, or evaluation thresholds in `evals/dataset.py` or `evals/evaluators.py` to make a failing eval pass.
- If a prompt test or eval fails, **report the failure** and wait for the developer to decide whether to update the prompt or the test. These changes must be conscious decisions, not automated fixes.

## Code Style

### Python (Backend)
- Python 3.12+ with type hints
- Ruff for linting (line-length: 100)
- Async/await for all I/O operations
- Pydantic for data validation
- Follow existing patterns in `src/core/` and `src/plugin_sdk/`

### TypeScript (Frontend)
- TypeScript with React 18
- ESLint with react-hooks plugin
- Functional components with hooks
- shadcn/ui for UI components
- Path alias: `@/*` → `./src/*`

### Naming Conventions
- **Modules/Plugins**: plural, snake_case (folders and `id`)
- **JS/TS fields**: camelCase
- **Database tables**: snake_case, plural (e.g., `users`, `chat_messages`)
- **Database columns**: snake_case (e.g., `created_at`, `user_id`)

### Internationalization (i18n)
- **No hardcoded user-facing strings in core-owned surfaces.** Every core UI text goes through a translation key — never inline a literal in a component, message, or template.
  - **Frontend**: `useTranslation()` + `t("ns:key")` (or `<Trans>` for markup); bundles live in `frontend/src/i18n/locales/{en,pl}/<ns>.json` (namespaces: `common`, `auth`, `chat`, `settings`, `errors`, `reasoning`). In non-component modules use the shared instance (`import i18n from "@/i18n"; i18n.t(...)`).
  - **Backend**: `translate("key", **params)` from `src.core.i18n`; catalogs live in `backend/src/core/locales/{en,pl}.py`.
  - **Keycloak**: `${msg("key")}` in `.ftl`; keys live in `themes/recordya/{login,email}/messages/messages_{en,pl}.properties` (Polish characters require `\uXXXX` escapes).
- The locale is **static and config-driven** via `DEFAULT_LOCALE` (single source of truth across frontend, backend, and Keycloak). No runtime switching, no browser detection; default `en`, with `pl` supported, and unknown values fall back to `en`.
- External plugin UI/nav-label i18n is not supported yet; keep plugin-facing localization decisions out of core until a plugin i18n API exists. See [`docs/i18n.md`](docs/i18n.md).

### General Guidelines
- Keep code minimal and focused; avoid side effects across modules
- No one-letter variable names
- Avoid in-line comments; prefer self-documenting code
- Keep exports minimal and typed
- Avoid casting to `any`; prefer precise types
- Keep commit messages and GitHub content clean and professional; do not add tool-generated attribution or trailers.

## Architecture Principles

- **YAGNI (You Aren't Gonna Need It)** - Do not add code, abstractions, or infrastructure for hypothetical future needs. Build only what is required by an existing plugin or feature. If no plugin uses it today, it should not exist.
- **KISS (Keep It Simple, Stupid)** - Prefer the simplest solution that works. One abstraction layer is better than three. A plain function is better than a class with one method.
- **DRY (Don't Repeat Yourself)** - Extract shared logic into a common base only when duplication actually exists across two or more concrete implementations. Do not preemptively create abstractions.
- **SOLID**:
  - **Single Responsibility** - Each class/module has one reason to change. AgentService orchestrates execution, not observability. Plugin defines domain logic, not streaming protocol.
  - **Open/Closed** - Core is open for extension (new plugins) but closed for modification. Adding a REST plugin should not require changes to AgentService or CoreEngine.
  - **Liskov Substitution** - Any subclass of `BasePlugin` must be usable wherever `BasePlugin` is expected. A `BaseSQLPlugin` instance must work anywhere a `ManagedPlugin` is accepted.
  - **Interface Segregation** - Do not force plugins to implement methods they don't need. `ExecutablePlugin` should not require `execute_tool()`, `ManagedPlugin` should not require `run()`.
  - **Dependency Inversion** - Core depends on abstractions (`BasePlugin`, `LLMProvider`), never on concrete implementations. Plugins depend on stable SDK interfaces, not internal core modules.
- **No dead code** - Do not commit unused classes, empty directories, or commented-out features. If code is not called from production paths, remove it.
- **One path, one mechanism** - Avoid parallel systems that do the same thing differently (e.g., two plugin interfaces, two observability integrations, two tool execution paths). Pick one and use it consistently.
- **Formal contracts over duck typing** - Plugin classes should inherit from explicit base classes (ABC) rather than relying on `hasattr()` checks or runtime-checkable Protocols. This enables IDE validation and catches errors at definition time. Exception: lightweight cross-cutting hooks (e.g. `ChatAccessGuard`) use `Protocol` + structural detection (`hasattr`) to avoid forcing plugins to import and subclass a core ABC for a two-method contract.

## UI Components (shadcn/ui)

The frontend uses shadcn/ui primitives located in `frontend/src/components/ui/`:

| Component | File | Description |
|-----------|------|-------------|
| Button | `button.tsx` | Primary action buttons |
| Card | `card.tsx` | Content containers |
| Dialog | `dialog.tsx` | Modal dialogs |
| Input | `input.tsx` | Text inputs |
| Select | `select.tsx` | Dropdown selects |
| Table | `table.tsx` | Data tables |
| Tabs | `tabs.tsx` | Tab navigation |
| Toast | `toast.tsx` | Notifications |
| Tooltip | `tooltip.tsx` | Hover tooltips |
| ScrollArea | `scroll-area.tsx` | Scrollable containers |

**Usage pattern:**
```tsx
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
```

## Plugin Development

### Plugin Hierarchy

```
BasePlugin (ABC)           ← metadata, lifecycle, health_check, suggestions
├── ExecutablePlugin       ← full control: run() yields events
├── ManagedPlugin          ← service-managed tool loop
│   └── BaseSQLPlugin      ← PostgreSQL convenience base
└── ViewPlugin             ← custom UI view (not a chat agent)

ChatAccessGuard (Protocol)  ← plugin-provided access control hook
```

- **Agent plugins** (`ExecutablePlugin`, `ManagedPlugin`) — appear in "Agents" sidebar, participate in chat, registered in `datasources` registry.
- **View plugins** (`ViewPlugin`) — appear in navigation rail (IconRail), render own full-page UI, registered in `view_plugins` registry.
- **Access guards** (`ChatAccessGuard`) — plugin-provided hooks that control access to chat (e.g. subscription expiry). Registered in `access_guards` registry, auto-discovered. Core calls all guards before processing `/api/agent/stream`. If no guards are registered, chat is unrestricted.

> `DataSourcePlugin` is a backward-compatibility alias for `ManagedPlugin`.

For full access guard documentation and examples, see: [`docs/plugin-development.md` — Access Guards](docs/plugin-development.md#access-guards-chatbot-access-control)

### ManagedPlugin Argument Preparation

When a managed plugin needs tool arguments that must be derived **deterministically** from the user's latest question, recent conversation history, or normalized before execution, implement `prepare_tool_arguments(tool_name, arguments, question=None, conversation_history=None)` in the plugin.

Use this hook to:
- enrich arguments from backend-side parsing of the user question,
- recover deterministic values from recent conversation history when the current turn is only a clarification answer,
- normalize or strip model-provided arguments before `execute_tool()`,
- keep domain-specific logic inside the plugin.

Do **not** push this logic into `AgentService` for a single plugin, and do **not** rely on prompt compliance alone when the backend needs a guaranteed value.

For hard product constraints, prefer backend enforcement inside the plugin flow:
- derive or normalize intent in `prepare_tool_arguments(...)`,
- enforce the effective constraint in `execute_tool(...)`,
- optionally return `user_notice` in a successful tool result when the backend must surface a deterministic user-visible notice.

Conversation memory across turns has two paths in `ConversationBuilder` (see [`docs/architecture.md` — Conversation Memory Across Turns](docs/architecture.md#conversation-memory-across-turns)): native tool-call replay (automatic, primary; uses persisted `tool_results`, with OpenAI-format `tool_calls` synthesized in-flight) and the legacy passive `[CONTEXT: Previously shown: ...]` block (opt-in via `ContextConfig`, used only when no `toolResults` are present in history). The `[CONTEXT:]` block is passive data only — it carries forward rows actually returned in `queryResults` but does not by itself guarantee exclusion/filtering in later turns.

For full plugin development guide, see: [`docs/plugin-development.md`](docs/plugin-development.md)

### Prompt Testing & Evaluation

Each plugin has two test layers: **structural tests** (pytest, offline) and **behavioural evals** (Langfuse, online). When creating or modifying a plugin's prompt, **read [`docs/prompt-testing.md`](docs/prompt-testing.md)** for the full guide.

**Shared eval SDK** (`backend/src/plugin_sdk/evals/`) provides:
- `make_hidden_columns_evaluator()`, `make_no_technical_leak_evaluator()` — heuristic evaluator factories
- `LLMJudge` — LLM-as-judge class (behaviour + hidden columns)
- `run_single_turn()` — runs one AgentService turn for evals
- `seed_prompt()`, `seed_dataset()`, `resolve_prompt_version()` — Langfuse seeding helpers
- `run_overall_score` — aggregate run-level evaluator

Each plugin's `evals/` directory contains: `dataset.py` (test cases), `evaluators.py` (heuristic evaluators using SDK factories), `llm_evaluators.py` (LLMJudge instance), `run_eval.py` (runner).

### Key Imports
```python
from src.plugin_sdk import (
    BasePlugin, ExecutablePlugin, ManagedPlugin, ViewPlugin, BaseSQLPlugin,
    CoreEngine, LLMRequest, LLMResponse, ToolCall, ToolResult,
    PluginManifest, create_tool_definition,
)

# For eval development:
from src.plugin_sdk.evals import (
    extract_content, extract_tool_history,
    make_hidden_columns_evaluator, make_no_technical_leak_evaluator,
    run_overall_score, run_single_turn, LLMJudge,
    seed_prompt, seed_dataset, resolve_prompt_version,
)
```

## Security Considerations

- **Authentication**: dual-mode — Keycloak SSO (RS256/JWKS) or local JWT (HS256/bcrypt). See [`docs/authentication.md`](docs/authentication.md)
- SQL plugins: SELECT-only queries, table whitelist (`allowed_tables`)
- Keyword blocking: INSERT, UPDATE, DELETE, DROP rejected
- Plugin owns security rules via PROMPT_TEMPLATE
- JWT authentication for all API endpoints
- Plugin `.env` files with secrets are gitignored

## API & Environment

For full details, see: [`docs/architecture.md`](docs/architecture.md) (sections 6–7)

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agent/stream` | POST | SSE streaming chat |
| `/api/config/models` | GET/PATCH | Model catalog + active model (GET any user; PATCH admin only) |
| `/api/datasources` | GET | List agent plugins (data sources) |
| `/api/datasources/{name}/health` | GET | Plugin health check |
| `/api/views` | GET | List view plugins (nav metadata) |
| `/api/plugins/{plugin_id}/...` | ANY | Plugin-owned HTTP endpoints |
| `/auth/config` | GET | Auth config (public, no auth) |
| `/auth/login` | POST | Login → JWT (local mode only) |
| `/auth/register` | POST | Register user (local mode only) |
| `/auth/me` | GET | Current user (both modes) |

### Environment Variables

**Backend** (root `.env`): `APP_DATABASE_URL`, `SECRET_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `DEFAULT_LLM_MODEL`, `DEFAULT_LOCALE`, `LANGFUSE_*`, `AUTH_MODE`, `KEYCLOAK_*`

**Frontend**: Runtime config via `/config/config.json` (default API URL: `http://localhost:8000`)
