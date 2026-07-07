# recordya-chat — Architecture

## 1. Project Overview

**recordya-chat** is a generic intelligent assistant platform with a pluggable data source architecture. The main application is completely agnostic to the underlying data - all domain knowledge resides in plugins.

### Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Frontend** | React 18 + TypeScript + Vite + Tailwind + shadcn/ui |
| **Backend** | Python 3.12 + FastAPI (async) |
| **Databases** | PostgreSQL (APP_DB for app data, plugin DBs for domain data) |
| **AI** | OpenAI-compatible API (OpenRouter, Fireworks, etc.) via LlmFacade |
| **Observability** | Langfuse (LLM tracing) |
| **Auth** | Keycloak SSO (OIDC) / local JWT + bcrypt |

### Module Structure

`recordya-chat` is designed to be used as a **git submodule**. Plugins live **outside** the core repo, in a sibling directory:

```
my-project/
├── core/              # recordya-chat (git submodule)
│   ├── frontend/      # React app (Vite)
│   ├── backend/       # Python API (FastAPI)
│   ├── keycloak/      # SSO config (realm seed, login theme)
│   └── docs/          # Architecture and plugin development docs
└── plugins/           # Plugin implementations (external to core)
    └── my_plugin/
        ├── backend/
        └── frontend/
```

> **Plugin discovery:** Both the backend and the frontend `@plugins` alias resolve plugins from the sibling `plugins/` directory (next to `core/`) — the same location in Docker Compose (mounted to `/plugins`) and in manual (non-Docker) runs. Deployment builds override this: the backend production image uses `/app/plugins`, and the CI frontend build uses a filtered `core/plugins` (which takes precedence whenever it contains staged plugin packages). The application starts normally when no plugins are present.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Frontend (React + Vite)                        │
│                    useAgentStream (SSE)                         │
└─────────────────────────┬───────────────────────────────────────┘
                          │ REST + SSE + JWT
┌─────────────────────────▼───────────────────────────────────────┐
│                  Backend (FastAPI)                              │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌───────────────────────────────────────┐    │
│  │ AuthService │  │           AgentService                │    │
│  │             │  │  (streaming agentic loop via SSE)     │    │
│  └──────┬──────┘  └─────────────────┬─────────────────────┘    │
│         │                           │                           │
│  ┌──────▼──────┐  ┌─────────────────▼─────────────────────┐    │
│  │ SQLAlchemy  │  │  LlmFacade + ModelPolicy              │    │
│  │   (ORM)     │  │  (OpenAI-compatible providers)        │    │
│  └──────┬──────┘  └─────────────────┬─────────────────────┘    │
│         │                           │                           │
│         │         ┌─────────────────▼─────────────────────┐    │
│         │         │     Plugin Registry (BasePlugin)      │    │
│         │         │  ┌─────────────────────────────────┐  │    │
│         │         │  │  Plugin (self-contained)        │  │    │
│         │         │  │  ExecutablePlugin → run()       │  │    │
│         │         │  │  ManagedPlugin → tool loop      │  │    │
│         │         │  │    └ BaseSQLPlugin (SQL)        │  │    │
│         │         │  │  ViewPlugin → custom UI view    │  │    │
│         │         │  │  ChatAccessGuard → access hook  │  │    │
│         │         │  └────────────────┬────────────────┘  │    │
│         │         └───────────────────┼───────────────────┘    │
└─────────┼─────────────────────────────┼────────────────────────┘
          │                             │
┌─────────▼─────────┐       ┌───────────▼───────────┐
│      APP_DB       │       │    Plugin's DB        │
│  (PostgreSQL)     │       │    (config.yaml)      │
└───────────────────┘       └───────────────────────┘
```

---

## 3. Backend Module

**Location:** `core/backend`

```
my-project/
├── plugins/                    # Plugin implementations (external to core)
│   └── <plugin_name>/
│       ├── backend/
│       │   ├── __init__.py
│       │   ├── plugin.py       # Plugin implementation
│       │   ├── schema.py       # Prompts
│       │   ├── tools.py        # Tool definitions
│       │   ├── manifest.yaml   # Plugin metadata
│       │   ├── config.yaml     # Config with $VAR placeholders (committed)
│       │   ├── .env            # Secrets (gitignored)
│       │   └── .env.example    # Secrets template (committed)
│       └── frontend/
│           ├── index.ts        # Registration
│           └── components/     # Plugin components
│
├── core/backend/
│   ├── src/
│   │   ├── core/
│   │   │   ├── config.py       # Pydantic Settings
│   │   │   ├── protocols.py    # BasePlugin hierarchy + HttpRoutablePlugin
│   │   │   ├── engine.py       # CoreEngine (LLM/tool primitives)
│   │   │   ├── discovery.py    # Plugin discovery (issubclass-based)
│   │   │   ├── registry.py     # PluginRegistry[BasePlugin], access_guards
│   │   │   ├── constants.py    # Shared constants
│   │   │   ├── exceptions.py   # Custom exceptions
│   │   │   ├── langfuse.py     # Langfuse integration
│   │   │   └── security.py     # Security utilities
│   │   │
│   │   ├── plugin_sdk/         # Stable SDK for plugin developers
│   │   │   ├── __init__.py     # Public exports
│   │   │   ├── sql.py          # BaseSQLPlugin base class
│   │   │   └── manifest.py     # PluginManifest Pydantic model
│   │   │
│   │   ├── services/
│   │   │   ├── agent.py           # AgentService
│   │   │   ├── agent_helpers.py   # ConversationBuilder, ToolExecutionService
│   │   │   ├── factory.py         # create_engine()
│   │   │   ├── observability.py
│   │   │   └── providers/
│   │   │
│   │   ├── api/
│   │   │   ├── routes/         # Core API routes
│   │   │   └── plugin_http.py  # Generic plugin-owned HTTP routing
│   │   └── ...
│   │
│   └── tests/
│
└── core/frontend/
    └── src/
        ├── plugins/            # Core plugin system
        │   ├── sdk.ts          # Frontend Plugin SDK (unified API)
        │   ├── registry.ts     # Runtime frontend plugin discovery
        │   ├── EventBus.ts     # Event-based communication
        │   ├── SlotRegistry.ts # UI injection points
        │   ├── ViewRegistry.tsx
        │   ├── TransformRegistry.ts
        │   ├── ResultRegistry.ts    # Plugin-driven query result rendering
        │   └── widgets/
        │       └── DefaultResultsTableWidget.tsx
        │
        └── components/
            ├── ChatMessage.tsx
            └── Slot.tsx
```

For plugin development, see: [`docs/plugin-development.md`](plugin-development.md)

---

## 4. Frontend

**Location:** `core/frontend`

```bash
cd core/frontend
npm install
npm run dev      # http://localhost:8080
```

### Module Structure

```
frontend/src/
├── components/
│   ├── ChatInterface.tsx       # Main chat UI
│   ├── ChatMessage.tsx         # Message rendering
│   ├── Slot.tsx                # Plugin UI slots
│   └── ui/                     # shadcn/ui components
│
├── plugins/                    # Plugin system
│   ├── sdk.ts                  # Frontend Plugin SDK (unified API)
│   ├── registry.ts             # Runtime plugin discovery/initialization
│   ├── EventBus.ts             # Event-based communication
│   ├── SlotRegistry.ts         # UI injection points
│   ├── ViewRegistry.tsx        # Custom plugin views/pages
│   ├── TransformRegistry.ts    # Message content transformations
│   ├── ResultRegistry.ts       # Query results rendering decisions
│   ├── WidgetRegistry.ts       # Core widget toolkit registry
│   └── widgets/                # Reusable plugin widgets
│       ├── DefaultResultsTableWidget.tsx
│       └── ChoicesWidget.tsx
│
├── hooks/
│   ├── useAgentStream.ts       # SSE client
│   ├── useChatHistory.ts       # Chat management
│   └── useAuth.ts              # Auth hook (Keycloak SSO + local JWT)
│
├── lib/
│   ├── config.ts               # Shared configuration (API_URL, auth config)
│   ├── api.ts                  # API client (authFetch, token management)
│   ├── auth-keycloak.ts        # Keycloak OIDC client (oidc-client-ts)
│   ├── auth-session.ts         # Session-expiry, single-flight refresh, cross-tab logout
│   └── agentStreamClient.ts    # SSE streaming client
│
└── utils/
    └── formatters.ts           # Value formatting utilities
```

### Key Concepts

- **Plugin SDK** - Unified API for plugin development (`createPluginSDK()`)
- **EventBus** - Plugins register handlers for events (e.g., welcome screen)
- **SlotRegistry** - Plugins inject UI into predefined slots
- **ViewRegistry** - Custom plugin views/pages with routing
- **TransformRegistry** - Message content transformations
- **ResultRegistry** - Plugins decide how query results are rendered (`default` table, `hide`, or custom widget)
- **WidgetRegistry** - Unified widget rendering registry for core and plugin widgets

### Result Widget Pipeline

Result widget rendering is a two-stage pipeline:

1. Tool history extraction selects the most recent successful widget payload (`_widget_type`, `_widget_payload`) if present; otherwise it falls back to the latest successful non-widget result.
2. `ResultRegistry` (plugin level) decides `render` / `hide` / `default`.
3. If plugin returns `default`, core checks `WidgetRegistry` using row metadata:
   - `_widget_type`: widget identifier (for example `make_choices`)
   - `_widget_payload`: widget-specific payload object
4. If no widget is resolved, core falls back to `DefaultResultsTableWidget`.
5. Interactive core widgets send follow-up user input in a machine-readable format (JSON block in chat message content) so multi-select answers remain unambiguous for LLM parsing. The user bubble renders only the human-readable segment.

This keeps plugin control over decision logic while giving core a reusable widget toolkit.

### Widget Visibility Rules

`WidgetRegistry` resolves widgets with explicit visibility semantics:

- **Core widgets** are always global and available to all plugins.
- **Plugin widgets** are private to the owner plugin by default.
- A plugin widget becomes globally available only if the plugin exports its type in manifest:
  - `frontend.public_widgets: ["widget_type"]`
- Owner matching for private widgets is based on the **message source plugin context** (`sourcePluginId`), with `agentId` used only as backward-compatible fallback for older message contexts.
- Runtime plugin initialization that mutates widget visibility (`setPluginPublicWidgets`) requires a local runtime import of the registry instance, not only re-export statements.

---

## 5. Databases

### APP_DB - Application Database

| Table | Description |
|-------|-------------|
| `users` | Users (email, hashed_password, role) |
| `chats` | Chat sessions (user_id, title, datasource) |
| `chat_messages` | Messages (chat_id, role, content, sql_query, results_json, `tool_results`, `reasoning_steps`) |
| `message_feedback` | Per-user feedback for assistant messages (`rating`, `saved_time`, `comment`) |
| `daily_usage` | Daily limits (user_id, date, query_count) |
| `system_settings` | Global key/value app settings (e.g. active LLM model) |

`chat_messages.reasoning_steps` is a `JSONB` column storing the per-turn agent trace (status updates, tool calls, results) used to rehydrate the super-admin reasoning panel after page reload. Writes are accepted only for `super_admin` users; reads return `null` for everyone else. The `POST /api/chats/{id}/messages` endpoint enforces a 200-step / 1 MB JSON cap to bound payload size.

`message_feedback` stores thumbs-up/down feedback for assistant responses. Feedback is unique per `(user_id, message_id)`, cascades with the parent chat/message, and uses a `rating` check constraint allowing only `positive` or `negative`. Positive feedback may include `saved_time`; both positive and negative feedback may include `comment`. The current user's feedback is returned with `GET /api/chats/{id}/messages` so the frontend can rehydrate selected thumbs after reload.

Plugins may also own tables in APP_DB for user-scoped features (e.g. favorites). These tables are created via `ensure_schema()` at startup, not through Alembic migrations, and are namespaced by plugin id (e.g. `{plugin_id}_favorites`).

### Plugin Databases

Each plugin manages its own database connection via `config.yaml`. The main application has no knowledge of plugin database schemas.

---

## 6. API Endpoints

### Authentication (`/auth`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/config` | GET | Auth mode config — public, no auth required |
| `/auth/register` | POST | Register (local mode only) |
| `/auth/login` | POST | Login → JWT (local mode only) |
| `/auth/me` | GET | Current user (both modes) |
| `/auth/usage` | GET | Usage stats |

See [`docs/authentication.md`](authentication.md) for full auth documentation.

### Agent Chat (`/api`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agent/stream` | POST | **SSE streaming** - main chat endpoint (see [`streaming.md`](streaming.md)) |
| `/api/datasources` | GET | Available agent plugins (data sources) |
| `/api/views` | GET | Available view plugins (nav metadata) |
| `/api/plugins/{plugin_id}/...` | ANY | Generic plugin-owned HTTP endpoints |

### Chat Management (`/api/chats`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/chats` | GET/POST | List/create chats |
| `/api/chats/{id}` | PATCH/DELETE | Update/delete |
| `/api/chats/{id}/messages` | GET/POST | Messages; `GET` includes current user's feedback per message |
| `/api/chats/{id}/messages/{message_id}/feedback` | POST | Create/update feedback for an assistant message |
| `/api/chats/{id}/messages/latest` | DELETE | Delete last N messages (retry); query param `count` (default 2, min 1, max 10) |
| `/api/chats/search/{query}` | GET | Search chats by title keyword |

Message feedback uses an upsert-style `POST`: submitting feedback again for the same user and message updates the existing row. The backend verifies that the chat belongs to the current user, the message belongs to that chat, and the message role is `assistant`.

Request payload:

- `rating`: `positive` or `negative`
- `saved_time`: optional, used for positive feedback only
- `comment`: optional free-text comment

The frontend only shows feedback actions for persisted assistant messages. While a new response is processing, the `Retry` action can disappear, but thumbs remain visible for previous assistant messages; feedback is hidden only for the currently streaming assistant response.

When an assistant message carries a `langfuse_trace_id` (captured from the `complete` SSE event and persisted on the message), submitting feedback also syncs a `user_feedback` score to the corresponding Langfuse trace via `score_user_feedback()`: `positive` maps to `1`, `negative` to `0`, the optional `comment` is forwarded, and `chat_id`/`message_id` are attached as score metadata. The score uses a stable `score_id` (`user_feedback-{message_id}`), so changing a rating upserts the existing score instead of appending a duplicate. The sync is best-effort — Langfuse failures are logged and swallowed so feedback persistence is never blocked. Messages without a `langfuse_trace_id` (e.g. when Langfuse is disabled) persist feedback locally without sending a score.

### Configuration (`/api/config`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config/models` | GET | Model catalog and the active model (any authenticated user) |
| `/api/config/models` | PATCH | Change the active LLM model (admin only) |

---

## 7. Environment Variables

### Backend (root `.env`)

```env
# Application Database
APP_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/app_db

# JWT (used when AUTH_MODE=local)
SECRET_KEY=your-secret-key-min-32-chars

# Authentication mode: "keycloak" (SSO) or "local" (email/password)
AUTH_MODE=keycloak

# Keycloak (used when AUTH_MODE=keycloak)
KEYCLOAK_URL=http://localhost:8180
KEYCLOAK_FRONTEND_URL=http://localhost:8180
KEYCLOAK_REALM=recordya
KEYCLOAK_CLIENT_ID=recordya-chat

# LLM Provider
OPENAI_API_KEY=xxx
OPENAI_BASE_URL=https://api.openai.com/v1
# Fallback model. The effective model is resolved as:
# request.model → system_settings (active model, set via PATCH /api/config/models) → DEFAULT_LLM_MODEL
DEFAULT_LLM_MODEL=gpt-5.2

# Langfuse (optional)
LANGFUSE_PUBLIC_KEY=pk-xxx
LANGFUSE_SECRET_KEY=sk-xxx
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_ENABLED=false

# Server
ENV=local               # also used as the native Langfuse Environment
CORS_ORIGINS=http://localhost:8080
PLUGINS_DIR=plugins

# Conversation memory (tool-call history replay)
CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET=8000   # max estimated tokens spent on replayed tool history
CONVERSATION_DEGRADED_MAX_ROWS=20             # row cap per tool result in `degraded` mode
CONVERSATION_MAX_TURNS=10                     # max past turns considered (newest kept)
```

---

## 8. Running

```bash
# Terminal 1 - Backend (from project root)
cd core/backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn src.main:app --reload --port 8000

# Terminal 2 - Frontend (from project root)
cd core/frontend
npm install && npm run dev
```

- Frontend: http://localhost:8080
- Backend API: http://localhost:8000/docs
- Langfuse: https://cloud.langfuse.com (if configured)

---

## 9. Plugin Architecture

### Philosophy

```
PLUGIN = "WHAT to do" (strategy, orchestration, agents, UI)
CORE   = "HOW to do it" (primitives, infrastructure, event bus)
```

Plugin has full control over logic and presentation. Core provides primitives and extensibility mechanisms.

### Plugin Hierarchy

```
BasePlugin (ABC)           ← metadata, lifecycle, health_check, suggestions
├── ExecutablePlugin       ← full control: run() yields events
│   └── (custom plugins)
├── ManagedPlugin          ← service-managed tool loop
│   └── BaseSQLPlugin      ← PostgreSQL convenience base
│       └── (SQL plugins)
└── ViewPlugin             ← custom UI view (not a chat agent)
    └── (view plugins)

ChatAccessGuard (Protocol)  ← plugin-provided access control hook
```

1. **ExecutablePlugin** — Plugin implements `run()` method, decides LLM calls, tools, orchestration, emits events
2. **ManagedPlugin** — Plugin provides system prompt, tools, execution; AgentService manages the agentic loop
3. **ViewPlugin** — Plugin provides a custom full-page UI view, appears in the navigation rail, does NOT participate in chat
4. **ChatAccessGuard** — Plugin-provided hook that controls access to the chat endpoint (e.g. subscription expiry). Registered in `access_guards` registry, called by core before processing chat requests. See [plugin-development.md — Access Guards](plugin-development.md#access-guards-chatbot-access-control).

> `DataSourcePlugin` is a backward-compatibility alias for `ManagedPlugin`.

### Tool Argument Preparation Hook

Managed plugins can deterministically normalize or enrich tool arguments before execution via `prepare_tool_arguments()`.

Flow:

1. `AgentService` creates `ToolExecutionService(question=question, conversation_history=conversation_history)` for the current user turn.
2. `ToolExecutionService.parse_tool_calls()` parses the model's tool-call JSON.
3. Before each tool runs, `ToolExecutionService` calls `plugin.prepare_tool_arguments(tool_name, arguments, question, conversation_history)`.
4. The returned arguments are then passed to `plugin.execute_tool()`.

This hook exists so domain-specific logic stays in the plugin instead of leaking into `AgentService` or prompt-only conventions. Use it when a value must come from the user's current turn, recent conversation history, or backend rules rather than from model compliance.

In practice, hard product constraints are best split across the managed-plugin flow like this:

- `prepare_tool_arguments()` derives or normalizes values that must come from the current question or recent history.
- `execute_tool()` enforces the effective backend constraint on the returned payload (for example trimming rows to a capped result count).
- A successful tool result may optionally include `user_notice` when the backend needs to surface a deterministic user-visible notice about what was enforced.
- `AgentService` may prepend the latest `user_notice` from successful tool history to the final assistant text, avoiding duplicate notice text when it is already present.

### Conversation Memory Across Turns

For ManagedPlugin conversations, `ConversationBuilder` (`agent_helpers.py`) preserves prior turns when constructing the LLM message list. Two mechanisms exist and they are mutually exclusive within a single call to `build_messages()`:

1. **Native tool-call replay** (primary, automatic) — reconstructs the original `assistant`+`tool_calls` / `tool` message sequence so the model sees full tool inputs and outputs from previous turns.
2. **Passive `[CONTEXT:]` block** (legacy, opt-in) — extracts data rows from prior `queryResults` widget payloads and prepends them as a text block to the latest user message.

The native path is taken whenever **any assistant message in `conversationHistory` has a non-empty `toolResults`**. The legacy `[CONTEXT:]` path is used only when no `toolResults` are present in history (e.g. plugins/agents whose persisted history predates the tool-history columns, or eval runners that forward only `queryResults`).

#### Native Tool-Call Replay

Persistence: every assistant turn that ran tools is saved to `chat_messages.tool_results` (one entry per tool execution with `tool` / `tool_name` / `tool_call_id` / `arguments` / `result` / `duration_ms`). The frontend forwards this field back to `/api/agent/stream` on the next user turn. The OpenAI-format `tool_calls` array is synthesized in-flight from `tool_results` by `_synthesize_tool_calls()`; it is not persisted separately.

`ConversationBuilder._build_tool_replay()` then:

1. Groups history into `(user, assistant)` turn pairs, keeping the last `CONVERSATION_MAX_TURNS` turns.
2. Pre-serializes each turn in three modes:
   - `full` — complete synthesized `assistant.tool_calls` and matching `tool` messages.
   - `degraded` — same native tool-call shape, but large list fields in each tool result are capped at `CONVERSATION_DEGRADED_MAX_ROWS`. Core truncates common payload shapes: `result` and `entries`. Truncated payloads include markers such as `_truncated`, `_result_truncated`, `_entries_truncated`, `_original_row_count`, `_original_entries_count`, `_retained_row_count`, and `_retained_entries_count`.
   - `text_only` — only the final assistant text from that turn is replayed; synthesized `assistant.tool_calls` and `tool` messages are omitted.
3. Greedily walks turns newest-first, picking the richest mode that still fits the global `CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET` (estimated at ~4 chars/token). Older turns degrade first; the most recent turn is always at least `text_only`.

The reconstructed sequence is appended to the system prompt before the current user question. No `[CONTEXT:]` block is emitted on this path.

Replay diagnostics are recorded outside the prompt: `AgentService` attaches a `conversation_replay` object to Langfuse metadata and logs truncation without tool arguments or result payloads. `degraded` replay is logged at `INFO`; `text_only` replay is logged at `WARNING`. The metadata includes aggregate fields such as `mode_counts`, `selected_modes`, `truncated`, `budget_initial`, `budget_remaining`, and `over_budget_turns`, plus per-turn token estimates.

#### Legacy `[CONTEXT:]` Block

When no `toolResults` are present in history, `ConversationBuilder` falls back to the original behaviour:

1. The last `CONVERSATION_MAX_TURNS * 2` history messages are appended as plain `user`/`assistant` text.
2. For assistant messages, `queryResults` widget payloads are unwrapped and rows are deduplicated by primary key.
3. A passive context block (`[CONTEXT: Previously shown: ...]`) is prepended to the current user question, listing previously shown results with their IDs.

The context block provides **data only** — it does not instruct the LLM to take any specific action. The plugin's `PROMPT_TEMPLATE` contains rules that tell the LLM how and when to use this context (e.g. excluding previously shown results when the user asks for alternatives).

Only rows actually returned in `queryResults` participate. Trimming a widget payload also trims what the next turn sees. This is intentionally separate from exclusion logic: the passive context block exposes prior results, but it does not itself guarantee that future calls will exclude them. Deterministic exclusion still has to be implemented in plugin/backend logic if prompt-only behaviour is not strong enough.

#### `ContextConfig`

The legacy `[CONTEXT:]` path is **opt-in**. A plugin enables it by overriding `get_context_config()` on `ManagedPlugin` and returning a `ContextConfig` instance:

| Field | Purpose |
|-------|---------|
| `data_widget_types` | `frozenset` of `_widget_type` values whose `_widget_payload.rows` should be collected. Unknown types are silently ignored. |
| `primary_key` | Row field used for deduplication across turns. |
| `display_field` | Row field used as a human-readable label in the `[CONTEXT:]` block. |

Plugins that do not override `get_context_config()` (default returns `None`) get no `[CONTEXT:]` injection on the legacy path. The native tool-replay path does not consult `ContextConfig` — it operates on `toolResults` regardless of plugin opt-in.

### Event Flow

```
Backend emits event → SSE → Frontend EventBus → Plugin handler → Custom rendering
```

For the full SSE protocol (event types, payload shapes, token streaming semantics, the leaked-tool guard and `token_reset` flow, and the provider chunk contract) see [`streaming.md`](streaming.md).

#### Role-Based SSE Redaction

`POST /api/agent/stream` filters events per consumer role before serialisation:

- `super_admin` — receives full event payloads (tool ids, arguments, results, errors).
- everyone else (incl. `admin`) — `status` events keep only `message` / `step`, `tool` events keep only `name` / `duration_ms`. All other event types pass through unchanged for backward compatibility.

Redaction lives in `chat.py::_redact_event` (single point of truth). The agent service itself is role-agnostic and always emits full data. The same role gate is applied at write time in `chats.py` (only `super_admin` clients can persist `reasoning_steps`) and at read time in `GET /api/chats/{id}/messages` (returns `null` for everyone except `super_admin`).

### Plugin HTTP Routing

Core supports optional plugin-owned HTTP routers mounted dynamically at startup:

- plugin implements `HttpRoutablePlugin` in backend
- plugin returns `APIRouter` via `get_api_router()`
- core mounts it under `/api/plugins/{plugin_id}/...`
- auth mode defaults to JWT (`authenticated`), with explicit `public` opt-out
- plugin response payloads are guarded by core size limits

### Frontend Plugin SDK

Unified API for frontend plugin development:

```typescript
import { createPluginSDK } from "@/plugins/sdk";

const sdk = createPluginSDK("my-plugin");

sdk.slot("detail.panel", MyPanel, { condition: (ctx) => ctx.agentId === "my-plugin" });
sdk.view("/my-page", MyPage);               // Register custom view
sdk.on("welcome.render", handleWelcome);    // Handle events
sdk.results((ctx) => ({ action: "default" })); // Result widget decision
sdk.widget("my_widget", (ctx, payload) => ({ action: "render", node: MyNode })); // Widget renderer
sdk.toolRenderer({ toolName: "execute_sql", target: "arguments", decide: (ctx) => ({ action: "render", node: MyToolPreview }) }); // Per-tool preview in super-admin reasoning panel
```

Core widget contract (optional on query rows):

```json
{
  "_widget_type": "make_choices",
  "_widget_payload": {
    "questions": [
      {
        "id": "q1",
        "prompt": "Question text",
        "allow_multiple": true,
        "allow_open_text": true,
        "options": [{"id": "opt_1", "label": "Option"}]
      }
    ]
  }
}
```

Frontend plugins are discovered at runtime from the external `plugins/*/frontend/index.{ts,tsx,js,jsx}` directory (sibling to `core/`).
`initializePlugins()` runs the loader during bootstrap in `main.tsx`.

### Observability

Observability (Langfuse, etc.) is transparent to plugins:
- Plugin calls `engine.call_llm()` → Core automatically logs
- Plugin doesn't know about observability providers
- Provider configured via env vars (`LANGFUSE_ENABLED`, `LANGFUSE_*`)
- The backend `ENV` value is sent as Langfuse's native Environment and is also
  kept in trace metadata for backwards-compatible filtering.

---

*Last updated: 2026-06-19*
