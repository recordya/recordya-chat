# Plugin Development Guide

## Overview

Each plugin is **fully self-contained** with its own config, prompt, and tools. The main application is generic - adding a new plugin requires **zero changes** to the core.

## Plugin Location

Plugins live **outside** the core repository, in a sibling `plugins/` directory:

```
my-project/
├── core/              # recordya-chat (git submodule)
│   ├── backend/
│   ├── frontend/
│   └── docker-compose.yml
└── plugins/           # Your plugins (sibling to core/)
    └── my_plugin/
        ├── backend/
        └── frontend/
```

- Both the **backend** and the frontend `@plugins` alias resolve plugins from the sibling `plugins/` directory (next to `core/`) — the same location in **Docker Compose** (mounted to `/plugins`) and in **manual (non-Docker)** runs.
- Deployment builds override this: the backend production image uses `/app/plugins`, and the CI frontend build uses a filtered `core/plugins` (which takes precedence whenever it contains staged plugin packages).
- The application starts normally when no plugins are present — the platform ships with zero plugins out of the box.

## Architecture Philosophy

```
PLUGIN = "WHAT to do" (strategy, orchestration, agents, UI)
CORE   = "HOW to do it" (primitives, infrastructure, event bus)
```

Plugin has full control over logic and presentation. Core provides primitives.

## Plugin Types

There are two categories of plugins:

- **Agent plugins** (`ExecutablePlugin`, `ManagedPlugin`) — Chat agents that appear in the "Agents" sidebar section, participate in conversations, and use the LLM-based agentic loop.
- **View plugins** (`ViewPlugin`) — Custom UI views that appear as icons in the navigation rail (IconRail). They render their own full-page UI and do NOT participate in chat.

### 1. ExecutablePlugin (Full Control)

For complex plugins that need custom orchestration, multi-agent systems, or non-standard workflows.

```python
# plugin.py
from collections.abc import AsyncGenerator
from typing import Any
from src.plugin_sdk import ExecutablePlugin, CoreEngine, LLMRequest, ToolCall

class MyPlugin(ExecutablePlugin):
    name = "my_plugin"
    display_name = "My Plugin"
    description = "Description for users"
    version = "1.0.0"

    async def run(
        self,
        engine: CoreEngine,
        question: str,
        session_id: str,
        model: str | None = None,
        **kwargs,
    ) -> AsyncGenerator[dict, None]:
        # Full control over execution
        yield engine.emit_status("Analyzing question...")

        response = await engine.call_llm(LLMRequest(
            messages=[
                {"role": "system", "content": self.get_system_prompt()},
                {"role": "user", "content": question},
            ],
            model=model or "gpt-5.2",
            tools=self.get_tools(),
        ))

        if response.tool_calls:
            for tc in response.tool_calls:
                call = ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=tc["function"]["arguments"])
                result = await engine.execute_tool(call, handler=self._execute_tool)
                yield engine.emit_tool(call.name, result.data)

        yield engine.emit_complete(response.content or "Done!")

    def get_tools(self) -> list[dict]:
        return [...]

    def get_system_prompt(self) -> str:
        return "..."

    async def _execute_tool(self, args: dict) -> dict:
        # Your tool implementation
        return {"success": True, "result": [...]}
```

### 2. ManagedPlugin (Service-Managed)

For simple SQL-based plugins where the service manages the agentic loop.

> `DataSourcePlugin` is a backward-compatibility alias for `ManagedPlugin`.

#### Deterministic Tool Argument Preparation

`ManagedPlugin` exposes an optional hook:

```python
def prepare_tool_arguments(
    self,
    tool_name: str,
    arguments: dict[str, Any],
    question: str | None = None,
    conversation_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return arguments
```

`ToolExecutionService` calls this hook **after** parsing the model's tool-call JSON and **before** `execute_tool()` runs.

Use it when a plugin needs to:

- derive tool arguments deterministically from the user's current question,
- recover deterministic arguments from recent conversation history when the current turn is only a clarification answer,
- normalize model-provided arguments before execution,
- remove arguments that should not be trusted from the model.

Typical example: a plugin wants to infer a display/result count from the user's latest question, or recover it from the immediately preceding request when the current turn is only a `make_choices` clarification answer, and enforce that value in the backend instead of relying on the LLM to pass it correctly.

Keep this logic **local to the plugin** unless the same mechanism is needed by multiple plugins.

For hard constraints, keep the responsibility split explicit:

- use `prepare_tool_arguments()` to derive or normalize the user's intended value,
- use `execute_tool()` to enforce the effective backend limit on the payload you actually return,
- and, if needed, include an optional `user_notice` in the successful tool result so the final assistant text can explain what the backend enforced.

#### Conversation Memory Across Turns

`ConversationBuilder` carries prior turns into the next LLM call using one of two mechanisms (it picks one per call):

1. **Native tool-call replay** — automatic for every ManagedPlugin. Persisted `tool_results` (saved to `chat_messages.tool_results` and round-tripped by the frontend) are replayed as real `assistant`+`tool_calls` / `tool` messages, so the model sees full tool inputs and outputs from earlier turns. The OpenAI-format `tool_calls` array is synthesized in-flight from `tool_results` (each entry carries `tool_call_id`, `tool_name`, and `arguments`). Older turns degrade or collapse to text only under a global token budget (`CONVERSATION_TOOL_HISTORY_TOKEN_BUDGET`, `CONVERSATION_DEGRADED_MAX_ROWS`, `CONVERSATION_MAX_TURNS`). In `degraded` mode, core caps common large list fields in tool results, including `result` and `entries`, so plugins can return document-search style payloads without custom replay code. **Nothing to configure on the plugin.**
2. **Legacy passive `[CONTEXT:]` block** — used as fallback when no `toolResults` are present in history (e.g. eval runners that only forward `queryResults`, or historical chats persisted before the tool-history columns existed). Opt-in via `get_context_config()`.

When **any** assistant message in `conversationHistory` has a non-empty `toolResults`, the native path is taken and no `[CONTEXT:]` block is emitted. Otherwise the legacy path runs and emits `[CONTEXT:]` only if the plugin opts in.

##### Legacy `[CONTEXT:]` opt-in (`ContextConfig`)

Override `get_context_config()` and return a `ContextConfig`:

```python
from src.plugin_sdk import ContextConfig

def get_context_config(self) -> ContextConfig:
    return ContextConfig(
        data_widget_types=frozenset({"my_results_widget"}),
        primary_key="item_id",
        display_field="name",
    )
```

| Field | Purpose |
|-------|---------|
| `data_widget_types` | Widget `_widget_type` values whose `_widget_payload.rows` are collected. |
| `primary_key` | Row field for deduplication across turns. |
| `display_field` | Row field shown as label in `[CONTEXT:]`. |

Plugins that do not override this method (default `None`) get no `[CONTEXT:]` injection on the legacy path. The context block provides data only — the plugin's `PROMPT_TEMPLATE` must include rules telling the LLM how to use it (e.g. when to exclude previously shown results and when not to).

Only rows actually stored in `queryResults` are preserved across turns. If your plugin trims the outgoing widget payload to 3 rows, the next turn's `[CONTEXT: Previously shown: ...]` will also see those 3 rows rather than any larger internal result set.

Context injection is not the same as deterministic exclusion. The context block exposes prior results to the model, but backend/plugin logic must still enforce exclusions if that behaviour must be guaranteed.

See [architecture.md — Conversation Memory Across Turns](architecture.md#conversation-memory-across-turns) for the full data flow, persistence schema, and budgeting algorithm.

### 3. ViewPlugin (Custom UI View)

For plugins that provide a standalone page/view instead of a chat agent. ViewPlugins appear as icons in the navigation rail and render their own full-page UI. They do **not** appear in the "Agents" sidebar section and are **not** registered as data sources.

```python
# plugin.py
from fastapi import APIRouter
from src.core.protocols import HttpRoutablePlugin, PluginRouteAuthMode, ViewPlugin

router = APIRouter()

@router.get("/items")
async def list_items() -> dict:
    return {"items": [{"id": 1, "name": "Example"}]}


class MyViewPlugin(ViewPlugin):
    """Custom view plugin.

    Metadata (name, display_name, description) is loaded from manifest.yaml
    by discovery. Only domain logic is defined here.
    """

    name = "my_view"

    def get_api_router(self) -> APIRouter:
        return router

    def get_api_auth_mode(self) -> PluginRouteAuthMode:
        return "authenticated"
```

Navigation metadata is defined in `manifest.yaml` under the `nav` key:

```yaml
# manifest.yaml
id: "my_view"
name: "My View"
description: "Custom UI view"

nav:
  icon: "layout-grid"     # Lucide icon name (shown in navigation rail)
  label: "My View"        # Tooltip / navigation label
  order: 10               # Sort order in the rail (lower = higher)
```

Frontend registration:

```typescript
// plugins/my_view/frontend/index.ts
import { createPluginSDK } from "@/plugins/sdk";
import { MyView } from "./components/MyView";

export function registerPlugin(): void {
  const sdk = createPluginSDK("my_view");

  sdk.view("/my-view", MyView, {
    showInNav: true,
    navLabel: "My View",
    navIcon: "layout-grid",
    navOrder: 10,
  });
}
```

> **Icons:** Any icon from [lucide.dev/icons](https://lucide.dev/icons) can be used. Specify the kebab-case name (e.g. `clipboard-list`, `layout-grid`, `bar-chart-3`) — the frontend resolves it dynamically at runtime.

> **Role-based visibility:** view plugins control who sees them in the rail via `roles: Role[]` (`Role = "super_admin" | "admin" | "user"`). When omitted, the view is admin-only by default (`super_admin` is a superset of `admin` and always sees admin views). End-user views must opt in explicitly (e.g. `roles: ["user"]` or `roles: ["admin", "user"]`). The same metadata gates client-side route access — authenticated users navigating to a view their role is not listed in are redirected to `/`.

**Key differences from agent plugins:**

| | Agent Plugin | View Plugin |
|---|---|---|
| Base class | `ExecutablePlugin` / `ManagedPlugin` | `ViewPlugin` |
| Appears in | "Agents" sidebar section | Navigation rail (IconRail) |
| Chat/LLM | Yes — participates in chat | No — renders own UI |
| Manifest key | `agent:` (icon, color) | `nav:` (icon, label, order) |
| Registry | `datasources` | `view_plugins` |
| API endpoint | `/api/datasources` | `/api/views` |

## Quick Start (SQL Plugin)

### 1. Create Plugin Structure

```
plugins/my_plugin/
├── backend/
│   ├── __init__.py          # Export: from .plugin import MyDataSource
│   ├── plugin.py            # Plugin class
│   ├── schema.py            # PROMPT_TEMPLATE
│   ├── tools.py             # SQL_TOOLS list
│   ├── manifest.yaml        # Plugin metadata (required for UI)
│   ├── config.yaml          # Config with $VAR placeholders (committed)
│   ├── .env                 # Secrets (gitignored)
│   └── .env.example         # Secrets template (committed)
└── frontend/                # Optional: custom UI components
    ├── index.ts             # Registration function
    └── components/          # Custom UI components
```

### 2. Plugin Class (SQL)

```python
# plugin.py
from typing import Any
from src.plugin_sdk import BaseSQLPlugin
from .schema import PROMPT_TEMPLATE
from .tools import SQL_TOOLS

class MyDataSource(BaseSQLPlugin):
    """My plugin.

    Metadata (display_name, description, version, suggestions) is loaded
    from manifest.yaml by discovery. Only domain logic is defined here.
    """

    # Fallback name if manifest.yaml is missing
    name = "my_plugin"

    PROMPT_TEMPLATE = PROMPT_TEMPLATE
    allowed_tables = frozenset({"table1", "table2"})

    def get_predefined_tools(self) -> list[dict[str, Any]]:
        return SQL_TOOLS

    async def _get_template_vars(self) -> dict[str, Any]:
        # Fetch dynamic data if needed
        return {"dynamic_section": "..."}
```

### 3. Prompt Template

```python
# schema.py
PROMPT_TEMPLATE = """
SECURITY RULES:
1. Generate ONLY SELECT queries
2. NEVER modify data

=== DATA SOURCE ===
Schema description...

{dynamic_section}

EXAMPLES:
- "Show top items" → SELECT ... LIMIT 10
"""
```

### 4. Tools

```python
# tools.py
SQL_TOOLS = [
    {
        "name": "top_items",
        "description": "Get top items. Use for best/popular queries.",
        "sql": "SELECT name, score FROM table1 ORDER BY score DESC LIMIT 10",
        "status_hint": "Loading...",  # Optional: UI status
    },
    {
        "name": "top_items_limited",
        "description": "Get top items with a caller-provided limit.",
        "sql": "SELECT name, score FROM table1 ORDER BY score DESC",
        "parameters": {  # Optional: JSON Schema exposed to the LLM
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "required": ["limit"],
        },
    },
]
```

When a predefined tool declares `parameters`, the schema is propagated into the OpenAI-compatible tool definition so the LLM can supply arguments. Override `_prepare_predefined_sql(tool, arguments) -> str` on the plugin to render the final SQL from those arguments (e.g. append `LIMIT`, substitute placeholders). Raise `ValueError` from the hook to surface a user-facing validation error.

### 5. Configuration

`config.yaml` is **committed** to the repository. It contains no secrets — only `$VAR` placeholders that are resolved automatically by `discovery.py` at startup from two sources (in priority order):

1. A sibling `.env` file in the plugin directory (loaded locally, **not** added to `os.environ`)
2. System environment variables (`os.environ`)

The plugin cannot read `.env` directly — discovery loads `config.yaml`, expands `$VAR` placeholders, and passes the resolved dict to `plugin.initialize()`.

```yaml
# config.yaml (committed — no secrets, only $VAR references)
connection_string: $MY_PLUGIN_CONNECTION_STRING
pool_size: 10
```

```bash
# .env (gitignored — sibling of config.yaml, contains actual secrets)
MY_PLUGIN_CONNECTION_STRING=postgresql://<user>:<password>@<host>:6543/<database>
```

```bash
# .env.example (committed — template for collaborators)
MY_PLUGIN_CONNECTION_STRING=postgresql://<user>:<password>@<host>:6543/<database>
```

Only `.env` files are gitignored (`plugins/*/backend/.env`).

---

## Quick Start (View Plugin)

View plugins provide custom full-page UI (tables, dashboards, forms) instead of chat. They appear as icons in the navigation rail.

### 1. Create Plugin Structure

```
plugins/my_view/
├── backend/
│   ├── __init__.py          # Export: from .plugin import MyViewPlugin
│   ├── plugin.py            # Plugin class (ViewPlugin + optional HttpRoutablePlugin)
│   └── manifest.yaml        # Plugin metadata with nav config (required)
└── frontend/
    ├── index.ts             # registerPlugin() — registers view in ViewRegistry
    └── components/
        └── MyView.tsx       # React component rendered as the view
```

### 2. Backend: manifest.yaml

```yaml
id: "my_view"
name: "My View"
description: "Custom UI view"
version: "1.0.0"
enabled: true                # Optional (default: true). Set to false to disable.

nav:
  icon: "layout-grid"       # Any Lucide icon name (kebab-case). See https://lucide.dev/icons
  label: "My View"          # Tooltip shown on hover in the navigation rail
  order: 10                 # Sort order in the rail (lower = higher; primary chat view = 0)
```

### 3. Backend: plugin.py

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from src.core.protocols import HttpRoutablePlugin, PluginRouteAuthMode, ViewPlugin

router = APIRouter()


@router.get("/items")
async def list_items() -> dict[str, Any]:
    return {"items": [{"id": 1, "name": "Example"}], "total": 1}


class MyViewPlugin(ViewPlugin):
    """Custom view plugin.

    Metadata (name, display_name, description) is loaded from manifest.yaml
    by discovery — no need to define them here.
    """

    name = "my_view"  # Must match manifest id

    # --- HttpRoutablePlugin (optional — only if you need API endpoints) ---

    def get_api_router(self) -> APIRouter:
        return router

    def get_api_auth_mode(self) -> PluginRouteAuthMode:
        return "authenticated"  # or "public"
```

### 4. Backend: \_\_init\_\_.py

```python
from .plugin import MyViewPlugin

__all__ = ["MyViewPlugin"]
```

> **Important:** Without `__init__.py`, discovery will not find the plugin class.

### 5. Frontend: index.ts

```typescript
import { createPluginSDK } from "@/plugins/sdk";
import { MyView } from "./components/MyView";

export function registerPlugin(): void {
  const sdk = createPluginSDK("my_view");

  sdk.view("/my-view", MyView, {
    showInNav: true,           // Show icon in the navigation rail
    navLabel: "My View",       // Tooltip label
    navIcon: "layout-grid",    // Lucide icon name (must match manifest nav.icon)
    navOrder: 10,              // Sort order (must match manifest nav.order)
    roles: ["admin", "user"],  // Roles that see this view (omit = admin-only)
  });
}
```

### 6. Frontend: MyView.tsx

```tsx
import { useEffect, useState } from "react";
import { request } from "@/lib/api";

interface Item {
  id: number;
  name: string;
}

export function MyView() {
  const [items, setItems] = useState<Item[]>([]);

  useEffect(() => {
    request<{ items: Item[] }>("/api/plugins/my_view/items")
      .then((data) => setItems(data.items))
      .catch(() => setItems([]));
  }, []);

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">My View</h1>
      <ul>
        {items.map((item) => (
          <li key={item.id}>{item.name}</li>
        ))}
      </ul>
    </div>
  );
}
```

### How it works

1. Backend discovery loads `MyViewPlugin` → `isinstance(ViewPlugin)` → registers in `view_plugins` (NOT `datasources`)
2. Plugin does **not** appear in the "Agents" sidebar section
3. `HttpRoutablePlugin` mounts API routes at `/api/plugins/my_view/...`
4. Frontend `registerPlugin()` registers the view in `ViewRegistry` with `showInNav: true`
5. `IconRail` resolves the Lucide icon by name (any icon from [lucide.dev/icons](https://lucide.dev/icons) works) and renders it in the rail
6. Clicking the icon renders `MyView` as a full-page view

> **No core changes needed.** Discovery, registry, routing, and IconRail handle everything automatically.

---

## Access Guards (Chatbot Access Control)

Plugins can register **access guards** — hooks that core calls before processing each chat request. This allows plugins to enforce access control (e.g. subscription expiry, usage limits) without core knowing any plugin-specific logic.

### Protocol

Core defines the `ChatAccessGuard` protocol in `src/core/protocols.py`:

```python
class ChatAccessGuard(Protocol):
    async def check_access(
        self, db: AsyncSession, user_id: UUID, datasource: str | None = None
    ) -> None:
        """Raise an HTTP exception (e.g. 403) if access should be denied.

        ``datasource`` is the target agent plugin name (``None`` when it
        cannot be resolved). Use it to gate access per plugin, or ignore it
        to gate all chat uniformly."""
        ...

    async def get_access_info(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        """Return extra fields to merge into the /usage response.
        Example: {"chat_restricted": True}
        Return an empty dict if there is nothing to add."""
        ...
```

### How It Works

1. Plugin implements a class with `check_access()` and `get_access_info()` methods
2. Plugin exports the class from its `backend/__init__.py`
3. Discovery auto-detects the guard (by checking for both methods) and registers it in `access_guards` registry
4. Core iterates over all registered guards before processing chat requests (`/api/agent/stream`)
5. Core merges extra fields from all guards into the `/auth/usage` response

If **no guards are registered**, there are no restrictions — chat works without any access control.

### Example Implementation

```python
# plugins/my_plugin/backend/access_guard.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import forbidden


class MyAccessGuard:
    """Deny chat access when subscription has expired."""

    async def check_access(
        self, db: AsyncSession, user_id: UUID, datasource: str | None = None
    ) -> None:
        result = await db.execute(
            text("SELECT access_until FROM my_plugin_subscriptions WHERE user_id = :uid"),
            {"uid": user_id},
        )
        row = result.first()
        if row is None:
            return  # No subscription record — no restriction
        if row[0] is not None and row[0] < datetime.now(timezone.utc):
            raise forbidden("Your subscription has expired.")

    async def get_access_info(self, db: AsyncSession, user_id: UUID) -> dict[str, Any]:
        result = await db.execute(
            text("SELECT access_until FROM my_plugin_subscriptions WHERE user_id = :uid"),
            {"uid": user_id},
        )
        row = result.first()
        if row is None:
            return {"access_expired": False}
        expired = row[0] is not None and row[0] < datetime.now(timezone.utc)
        return {"access_expired": expired}
```

Register it via `__init__.py`:

```python
# plugins/my_plugin/backend/__init__.py
from .access_guard import MyAccessGuard

__all__ = ["MyAccessGuard"]
```

> **No core changes needed.** Discovery finds the guard automatically and registers it in `access_guards`.

### Multiple Guards

Multiple plugins can register independent guards. Core calls all of them — if **any** guard raises an exception, access is denied. The `/usage` endpoint merges extra fields from all guards into a single response.

---

## Reference

### Plugin Hierarchy

```
BasePlugin (ABC)           ← metadata, lifecycle, health_check, suggestions
├── ExecutablePlugin       ← full control: run() yields events
├── ManagedPlugin          ← service-managed tool loop
│   └── BaseSQLPlugin      ← PostgreSQL convenience base
└── ViewPlugin             ← custom UI view (not a chat agent)

ChatAccessGuard (Protocol)  ← plugin-provided access control hook
```

### BasePlugin (shared by all plugins)

| Method | Description |
|--------|-------------|
| `name`, `display_name`, `description`, `version` | Metadata (class attributes) |
| `initialize(config)` | Setup (called on startup) |
| `shutdown()` | Cleanup |
| `health_check() -> bool` | Connection check |
| `get_suggestions() -> list[str]` | UI example prompts |

### ManagedPlugin (extends BasePlugin)

| Method | Description |
|--------|-------------|
| `get_system_prompt() -> str` | Complete LLM prompt |
| `get_tools_definition() -> list[dict]` | OpenAI tools format |
| `prepare_tool_arguments(name, args, question=None, conversation_history=None) -> dict[str, Any]` | Optional hook to deterministically normalize/enrich arguments before tool execution |
| `execute_tool(name, args) -> dict[str, Any]` | Run tool and return payload/result metadata |

#### Local FastMCP tools

Plugins may register local typed tools through the stable Plugin SDK FastMCP
integration. This lets plugin authors write ordinary typed Python functions and
use FastMCP for schema generation and validation while `AgentService` continues
to call `get_tools_definition()` / `execute_tool()`.

For plugins whose local tools come solely from FastMCP, extend
`FastMCPManagedPlugin`: `populate_mcp()` is the single source of truth and the
base class implements `get_tools_definition()` / `execute_tool()` for you.

```python
from src.plugin_sdk import FastMCP, FastMCPManagedPlugin


class MyPlugin(FastMCPManagedPlugin):
    name = "my_plugin"

    async def get_system_prompt(self) -> str:
        return "You are a helpful plugin."

    def populate_mcp(self, mcp: FastMCP) -> None:
        mcp.tool(meta={"status_hint": "Listing items..."})(self.list_items)

    async def list_items(self, limit: int = 10) -> dict[str, Any]:
        """List items."""
        return {"success": True, "result": [], "row_count": 0}
```

Use FastMCP `meta={"status_hint": "..."}` to attach Recordya UI status
hints to local FastMCP tools.

If you override `initialize()`, call `await super().initialize(config)` after
your own setup so tool definitions are ready before discovery validates
manifest-declared global tools.

Hybrid plugins that merge local FastMCP tools with another tool source (e.g. a
remote MCP server) should keep using the lower-level
`create_fastmcp_tool_adapter()` and implement their own
`get_tools_definition()` / `execute_tool()` merging.

#### Global tools

Plugins can share tools with other plugins without any direct dependency.
"Globalness" is purely declarative — an exported tool is a regular entry of
the plugin's `get_tools_definition()` and executes through its standard
`execute_tool()`; there is no separate implementation channel.

**Provider** — export a tool with one line in `manifest.yaml`:

```yaml
provides_global_tools:
  - "format_table"
```

**Consumer** — opt in via `manifest.yaml` (only listed tools are added to that
plugin's agent loop; other agents never see them):

```yaml
requires_global_tools:
  - "format_table"
```

Validation is fail-fast at startup — each of these errors aborts application
startup:

- a `manifest.yaml` that fails `PluginManifest` schema validation (a missing
  manifest is fine; an invalid one is a hard configuration error),
- a declared name absent from the provider's `get_tools_definition()`,
- a tool-name collision between two providers (registration is all-or-nothing
  per plugin),
- a required tool with no provider in the deployment.

When the LLM calls a global tool, `CompositeToolProvider` routes the call to
the owning plugin's `execute_tool()`. On a name collision the consumer's own
local tool takes priority (shadows the global one).

Global tools receive all their input through regular tool arguments — there is
no implicit shared state between tools.

**Authorization:** `ChatAccessGuard` controls only whether a user can open a
chat with the active plugin in the UI. It is not checked again when that plugin
calls a global tool owned by another plugin. Treat `provides_global_tools` as a
public API for other plugins; if a tool needs per-user restrictions, implement
them inside the tool itself.

### BaseSQLPlugin (for SQL sources)

Provides: PostgreSQL pool, SQL validation, tool routing, prompt templating.

**Required overrides:**
- `PROMPT_TEMPLATE` - prompt with `{placeholders}`
- `allowed_tables` - whitelist
- `get_predefined_tools()` - SQL tools list
- `_get_template_vars()` - placeholder values

**Optional overrides:**
- `get_tools_definition()` - customize tool format
- `prepare_tool_arguments()` - derive or normalize tool arguments before `execute_tool()`
- `_prepare_predefined_sql(tool, arguments) -> str` - render SQL for a predefined tool from caller arguments (default: returns `tool["sql"]` unchanged); raise `ValueError` for user-facing validation errors
- `get_suggestions()` - UI prompts (default: empty)

### ViewPlugin (for custom UI views)

Marker class — no additional abstract methods beyond `BasePlugin`. Navigation metadata comes from `manifest.yaml` (`nav` key). Combine with `HttpRoutablePlugin` to expose custom API endpoints.

| Manifest Key | Description |
|---|---|
| `nav.icon` | Lucide icon name for the navigation rail |
| `nav.label` | Tooltip / label |
| `nav.order` | Sort order (lower = higher, default: 10) |

### ToolResult

```python
{
    "success": bool,
    "result": list[dict] | None,
    "row_count": int,
    "sql": str,
    "tool_type": "predefined" | "custom",
    "user_notice": str | None,
    "error": str | None
}
```

Notes:

- `user_notice` is optional. Use it for short deterministic backend notices that should be surfaced to the user after a successful tool call.
- `AgentService` may prepend the latest successful `user_notice` to the final assistant text, while avoiding duplicate insertion if the text already contains that notice.
- This is a good fit for hard backend-enforced behaviour such as capping an excessive requested result count while preserving the user-facing explanation outside prompt-only logic.

## API Endpoints

```
GET  /api/datasources                      # List agent plugins
GET  /api/datasources/{name}               # Agent plugin info
GET  /api/datasources/{name}/health        # Health check
GET  /api/datasources/{name}/suggestions   # Example prompts
GET  /api/views                            # List view plugins (nav metadata)
POST /api/agent/stream                     # Chat (SSE)
ANY  /api/plugins/{plugin_id}/...          # Optional plugin-owned HTTP endpoints
```

### Plugin-owned HTTP Endpoints (Backend)

Core supports optional plugin-specific HTTP routing.
If a plugin exposes the following methods, core mounts its router automatically under:

- `/api/plugins/{plugin_id}/...`

Contract methods:

- `get_api_router() -> APIRouter`
- `get_api_auth_mode() -> "authenticated" | "public"` (optional, default: `authenticated`)

Example:

```python
from fastapi import APIRouter
from src.plugin_sdk import BaseSQLPlugin


class MyDataSource(BaseSQLPlugin):
    name = "my_plugin"

    def get_api_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/items")
        async def list_items() -> dict:
            return {"items": []}

        return router

    def get_api_auth_mode(self) -> str:
        return "authenticated"  # or "public"
```

#### Mixed Auth Mode

When `get_api_auth_mode()` returns `"public"` (e.g. for media endpoints that cannot attach headers), the **entire router** is mounted without JWT middleware. Endpoints that still need authentication must inject `CurrentUser` and `DBSession` explicitly:

```python
from src.api.dependencies import CurrentUser, DBSession

def get_api_router(self) -> APIRouter:
    router = APIRouter()

    # Public — no auth needed (e.g. media served by <audio>/<img> elements)
    @router.get("/media/{file_id}")
    async def stream_media(file_id: str) -> Response:
        ...

    # Authenticated — inject CurrentUser explicitly
    @router.get("/bookmarks")
    async def list_bookmarks(current_user: CurrentUser, db: DBSession) -> dict:
        ...

    return router

def get_api_auth_mode(self) -> str:
    return "public"  # router-level auth off; per-endpoint auth via CurrentUser
```

### Plugin-owned HTTP Endpoints (Frontend)

All authenticated requests from plugin frontends must go through `authFetch` from `@/lib/api` — never call `fetch()` directly with an `Authorization` header. `authFetch` injects the bearer token, performs a single-flight silent refresh on `401`, and participates in the global session-expiry / cross-tab logout flow described in [`docs/authentication.md` — Session Lifecycle](authentication.md#session-lifecycle-frontend).

```ts
import { authFetch } from "@/lib/api";

async function fetchItems(): Promise<Item[]> {
  const response = await authFetch("/api/plugins/my_plugin/items");
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

// SSE streams: pass the AbortSignal through `init`
const ctrl = new AbortController();
const stream = await authFetch("/api/plugins/my_plugin/events", {
  signal: ctrl.signal,
});
```

For non-replayable bodies (`ReadableStream`, single-use `FormData`), `authFetch`'s `401` retry will fail — handle the refresh path yourself if you need to upload streams.

---

## Plugin-Owned Tables in APP_DB

Plugins may own tables in APP_DB for user-scoped features (e.g. favorites, bookmarks). Guidelines:

1. **Namespace** - prefix table name with plugin id: `{plugin_id}_favorites`, not `favorites`
2. **Schema management** - use `ensure_schema()` at startup (not Alembic), creating the table idempotently via `CREATE TABLE IF NOT EXISTS`
3. **Lifecycle** - call `ensure_schema()` from `initialize()` so the table exists before any request
4. **Access** - use `DBSession` dependency from core (`src.api.dependencies`) in API route handlers
5. **No ORM models** - use raw SQL (`text()`) to keep plugin decoupled from core's SQLAlchemy model registry

Example store class:

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from src.db.app_database import engine as app_db_engine

class MyPluginStore:
    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self._engine = engine or app_db_engine

    async def ensure_schema(self) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS my_plugin_favorites (
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    item_id BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (user_id, item_id)
                )
            """))
```

Wire it in the plugin:

```python
class MyDataSource(BaseSQLPlugin):
    def __init__(self) -> None:
        super().__init__()
        self._store = MyPluginStore()

    async def initialize(self, config: dict[str, Any]) -> None:
        await super().initialize(config)
        await self._store.ensure_schema()
```

---

## Security

1. **SELECT-only** - non-SELECT queries rejected
2. **Keyword blocking** - INSERT, UPDATE, DELETE, DROP
3. **Table whitelist** - only `allowed_tables` queryable
4. **Prompt control** - plugin owns security rules

---

## Production Deployment

For pip-installable plugins, use entry points:

```toml
# pyproject.toml
[project.entry-points."nexo.datasources"]
my_plugin = "my_package:MyDataSource"
```

---

### 6. Plugin Manifest

`manifest.yaml` is **required** for the plugin to appear in the UI with proper metadata (name, icon, color, welcome view, suggestions).

Discovery loads the manifest and sets `display_name`, `description`, `version`, and `suggestions` on the plugin instance — so you don't need to define them as class attributes.

#### Agent plugin manifest

```yaml
# manifest.yaml
id: "my_plugin"
name: "My Plugin"
description: "Description"
version: "1.0.0"
enabled: true              # Optional (default: true). Set to false to hide plugin from UI and skip loading.

agent:
  icon: "database"        # Lucide icon name
  color: "#8B5CF6"        # Brand color

welcome:
  title: "Welcome title"
  description: "Welcome description"
  suggestions:
    - text: "Example query"
      icon: "search"

# Optional: expose widget types globally to other plugins
frontend:
  public_widgets:
    - "shared_widget_type"

# Optional: cross-plugin tool sharing (see "Global tools" in Reference)
provides_global_tools:      # export own tools to other plugins
  - "format_table"
requires_global_tools:      # opt in to tools exported by other plugins
  - "format_table"
```

#### View plugin manifest

```yaml
# manifest.yaml
id: "my_view"
name: "My View"
description: "Custom UI view"
version: "1.0.0"
enabled: true              # Optional (default: true). Set to false to hide from UI and skip loading.

nav:
  icon: "clipboard-list"  # Lucide icon name (shown in navigation rail)
  label: "My View"        # Tooltip / navigation label
  order: 10               # Sort order in the rail (lower = higher, default: 10)
```

> **Note:** `enabled: false` disables the plugin on **both** backend and frontend. The frontend plugin loader also reads the manifest and skips registration when `enabled` is `false`.

---


## Frontend Plugin

Plugins can also have frontend components for custom result rendering.
Frontend plugin code lives alongside backend code in the unified `plugins/` folder.

### Structure

```
plugins/my_plugin/
├── backend/           # Backend plugin code
│   └── plugin.py
└── frontend/          # Frontend plugin code
    ├── index.ts       # Registration function (explicit, no side-effects)
    └── components/
        └── WelcomeView.tsx
```

### Registration (using Plugin SDK)

```typescript
// plugins/my_plugin/frontend/index.ts
import { createPluginSDK, type PluginEvent, type WelcomeEventData } from "@/plugins/sdk";
import { MyWelcomeView } from "./components/WelcomeView";
import { createElement } from "react";

const PLUGIN_ID = "my_plugin";

function handleWelcome(event: PluginEvent<WelcomeEventData>) {
  return createElement(MyWelcomeView, {
    title: event.data.title,
    description: event.data.description,
    suggestions: event.data.suggestions,
  });
}

// Export registration function (no auto-execution!)
// Runtime loader looks for this exact export name.
export function registerPlugin(): void {
  const sdk = createPluginSDK(PLUGIN_ID);

  // Register event handler
  sdk.on("welcome.render", handleWelcome);

  // Register UI slots (optional)
  // sdk.slot("detail.panel", MyPanel, { condition: (ctx) => ctx.agentId === PLUGIN_ID });

  // Register custom views (optional)
  // sdk.view("/my-page", MyPage, { showInNav: true, navLabel: "My Page" });

  // Register result renderer (optional)
  // sdk.results((context) => ({ action: "default" })); // default table
  // sdk.results((context) => ({ action: "hide" }));    // no result widget
}
```

### Runtime Discovery

Frontend plugins are discovered automatically from the `plugins/` directory (sibling to `core/`).

- Loader pattern: `@plugins/*/frontend/index.{ts,tsx,js,jsx}`
- Required export: `registerPlugin()`
- Backward compatibility: legacy `registerXxxPlugin()` exports are still supported.

No manual import in `frontend/src/plugins/registry.ts` is needed when adding a new plugin.
Core runtime modules that call registry methods during plugin bootstrap must import the concrete registry instance locally; re-exporting it from the same module is not sufficient for runtime access.

---

## Plugin SDK

### Backend SDK

Use the stable SDK instead of importing from `src.core` directly:

```python
from src.plugin_sdk import (
    BasePlugin,            # Shared ABC for all plugin types
    ExecutablePlugin,      # ABC for full-control plugins (run())
    ManagedPlugin,         # ABC for service-managed plugins (tool loop)
    ViewPlugin,            # ABC for custom UI view plugins (not chat agents)
    BaseSQLPlugin,         # Concrete base for SQL-based ManagedPlugin (PostgreSQL)
    CoreEngine,            # Engine interface for LLM calls
    LLMRequest,
    LLMResponse,
    ToolCall,
    ToolResult,
    PluginManifest,        # Pydantic model for manifest validation
    create_tool_definition,
)
```

#### BaseSQLPlugin

For plugins that query PostgreSQL databases:

```python
from src.plugin_sdk import BaseSQLPlugin

class MyDataPlugin(BaseSQLPlugin):
    name = "my_data"
    display_name = "My Data Plugin"

    # Prompt template with placeholders
    PROMPT_TEMPLATE = """You are a data assistant.
Schema: {schema}
Allowed tables: {allowed_tables}"""

    # Whitelist of queryable tables
    allowed_tables = frozenset({"products", "orders"})

    def get_predefined_tools(self) -> list[dict]:
        """Define SQL tools available to the LLM."""
        return [
            {
                "name": "get_all_products",
                "description": "Get all products",
                "sql": "SELECT * FROM products LIMIT 100"
            }
        ]

    async def _get_template_vars(self) -> dict:
        """Provide values for PROMPT_TEMPLATE placeholders."""
        return {
            "schema": "products(id, name, price), orders(id, product_id, qty)",
            "allowed_tables": ", ".join(self.allowed_tables)
        }

# Plugin is initialized with config containing connection_string:
# await plugin.initialize({"connection_string": os.getenv("MY_DATABASE_URL")})
```

#### PluginManifest

For validating plugin manifest.yaml files:

```python
from src.plugin_sdk import PluginManifest
import yaml

with open("manifest.yaml") as f:
    data = yaml.safe_load(f)
    manifest = PluginManifest(**data)  # Validates structure
```

### Frontend SDK

Use `createPluginSDK()` for unified frontend plugin API:

```typescript
import { createPluginSDK } from "@/plugins/sdk";

const sdk = createPluginSDK("my-plugin");

// Available methods:
sdk.slot(name, component, options?)   // Register UI slot component
sdk.view(path, component, options?)   // Register custom view/page
sdk.viewLazy(path, loader, options?)  // Register lazy-loaded view
sdk.transform(fn, options?)           // Register text transformer
sdk.renderer(fn, options?)            // Register content renderer
sdk.results(fn, options?)             // Decide result widget: default/hide/custom node
sdk.widget(type, fn, options?)        // Register widget renderer for _widget_type
sdk.toolRenderer(options)             // Per-tool preview in super-admin reasoning panel
sdk.referenceSuggestions(fn, options?) // Provide "@" mention suggestions for the chat composer
sdk.conversationReferences(type, fn)  // Map a widget payload to the references it displays
sdk.formatConfig(config)              // Per-plugin formatting (locale, duration labels/columns)
sdk.on(eventType, handler)            // Register event handler
sdk.emit(eventType, data)             // Emit event
sdk.unregisterAll()                   // Cleanup (for tests)
```

#### Format Config

`sdk.formatConfig(config)` registers a `PluginFormatConfig` keyed by `sourcePluginId`, applied to that plugin's chat messages:

| Field | Type | Description |
|---|---|---|
| `locale` | `string` | BCP 47 locale used for number/duration formatting. |
| `durationLabels` | `{ hour, minute }` | Words appended after hour/minute parts in `formatDuration`. |
| `durationColumnNames` | `readonly string[]` | DB column names holding durations expressed in minutes. |

#### Content Transforms

`sdk.transform(fn, options?)` registers a text-to-text transformer applied to assistant message content before rendering. Transformers run in ascending `priority` order (default `100`); each may declare a `condition` to opt out. The transformer and its condition receive a `TransformContext`:

| Field | Type | Description |
|---|---|---|
| `messageId` | `string?` | ID of the message being rendered. |
| `agentId` | `string?` | Active agent. |
| `sourcePluginId` | `string?` | Plugin that produced the message (falls back to `agentId`). Scope a transform to its own plugin by matching this. |
| `hasResults` | `boolean?` | `true` when the message also carries rendered results (a widget or the default results table shown separately). |
| `isStreaming` | `boolean?` | Whether the message is still streaming. |

The registry is global, so a transform fires for every plugin's messages — always scope it via `sourcePluginId`.

**Stripping markdown tables:** assistant text renders verbatim by default, including markdown tables the LLM authored. When a plugin renders its results separately (the default results table or a custom widget), the LLM's inline table is a duplicate. Such plugins opt in to stripping by registering a transform scoped to their own messages that carry results, using the re-exported `stripMarkdownTables` helper:

```typescript
import { createPluginSDK } from "@/plugins/sdk";
import { stripMarkdownTables } from "@/plugins/registry";

const PLUGIN_ID = "my_plugin";

export function registerPlugin(): void {
  const sdk = createPluginSDK(PLUGIN_ID);

  sdk.transform((text) => stripMarkdownTables(text), {
    condition: (_text, context) =>
      context?.sourcePluginId === PLUGIN_ID && context?.hasResults === true,
  });
}
```

Plugins that should keep inline tables (e.g. those whose answers cite tables alongside other rendered content) simply register no such transform.

#### UI Slot Catalog

Core renders named injection points at fixed locations. Register a component for a slot via `sdk.slot(name, Component, options?)`. The `SlotName` union in `core/frontend/src/plugins/SlotRegistry.ts` is the source of truth — only the slots listed below are actually rendered by core; any additional names in the union are reserved.

| Slot name | Render location | Context |
|---|---|---|
| `detail.panel` | Top of the chat area in `ChatInterface` (above the message list) | `agentId`, `currentChatId`, `messages`, `isProcessing`, `setComposerText`, `submitUserMessage` |
| `chat.welcome` | Empty-state welcome area shown before the first message | same as `detail.panel` |
| `chat.input.before` | Slot rendered directly above the chat composer | same as `detail.panel` |
| `chat.input.after` | Slot rendered directly below the chat composer | same as `detail.panel` |
| `chat.message.content` | Per-message slot rendered between the assistant text and any widgets | `agentId`, `messageId`, `message`, `sourcePluginId`, `submitUserMessage`, `setComposerText` |
| `chat.message.actions` | Per-message actions row (next to copy/regenerate) | same as `chat.message.content` |
| `settings.users.row.header` | Header cell of the admin Users table (one slot column shared by all plugins) | _empty_ |
| `settings.users.row.extra` | Body cell of the admin Users table, rendered once per user row | `user: UserResponse` |
| `settings.users.add.fields` | Extra form fields in the "Add user" popover | `pluginData`, `setPluginData` |

Use `condition` in `options` to gate a slot per agent or message source, e.g. `sdk.slot("detail.panel", Panel, { condition: (ctx) => ctx.agentId === PLUGIN_ID })`. Use `order` to position components when multiple plugins register for the same slot (lower renders first; default `100`).

To gate UI on the presence of another plugin, use `isPluginInitialized(pluginId)` from `@/plugins/registry` — it returns `true` when that plugin is enabled in its manifest and registered.

### Result Rendering

Frontend plugins can control how SQL/query results are shown in chat messages:

- `action: "default"` - use built-in table widget (default fallback)
- `action: "hide"` - hide result widget
- `action: "render"` - return a custom React node

`ResultRenderContext` includes: `agentId`, `sourcePluginId`, `messageId`, `content`, `sql`, `sqlMode`, `queryResults`, `fields`, `durationFields`.

It also exposes optional UI actions for interactive widgets:

- `submitUserMessage(text)` - send a new user message from widget interaction
- `setComposerText(text)` - prefill chat composer text without sending
- `addComposerReference(reference)` - attach a `ComposerReference` chip to the composer (see "Composer References")

Reusable widget:

- `DefaultResultsTableWidget` is exported from `@/plugins/registry` and can be reused by plugin renderers. It accepts the render `context` plus an optional `pageSize` prop (rows per page; defaults to 10).

Example custom renderer:

```typescript
import { createElement } from "react";
import { createPluginSDK, DefaultResultsTableWidget } from "@/plugins/registry";

const sdk = createPluginSDK("my_plugin");

sdk.results((context) => {
  if (context.agentId !== "my_plugin") {
    return { action: "default" };
  }
  if (context.queryResults.length === 0) {
    return { action: "hide" };
  }
  return {
    action: "render",
    node: createElement(DefaultResultsTableWidget, { context }),
  };
});
```

### Tool Preview Rendering (Super-Admin Reasoning Panel)

Plugins can supply custom previews for individual tool calls displayed in the `super_admin`-only `ReasoningPanel`. Use `sdk.toolRenderer({ toolName, target, decide })`:

- `toolName` — name of the tool to customise (matches `ToolCall.name`)
- `target` — `"arguments"` (input preview) or `"result"` (output preview)
- `decide(context)` returns `{ action }`:
  - `"default"` — fall back to the built-in JSON preview
  - `"hide"` — render nothing
  - `"render"` — return a custom React node via `node`

`ToolRenderContext` includes: `toolId`, `toolName`, `agentId`, `sourcePluginId`, `status` (`"running" | "done" | "error"`), `arguments`, `result?`, `durationMs?`, `rowCount?`, `error?`.

Renderers are scoped to their owning plugin: a plugin's renderer only fires when `context.sourcePluginId` (or `agentId` fallback) matches the plugin id. Multiple registered renderers are tried in priority order (lower first); the first one returning `default`, `hide`, or `render` with a non-null node wins.

> **Visibility:** the reasoning panel and tool previews are only rendered for users with the `super_admin` role. The backend strips tool ids, arguments, and results from SSE events for everyone else (including `admin`), and `GET /api/chats/{id}/messages` returns `reasoning_steps: null` for them. Plugin renderers therefore never receive non-super-admin context.

Example:

```typescript
import { createElement } from "react";
import { createPluginSDK } from "@/plugins/registry";

const sdk = createPluginSDK("my_plugin");

sdk.toolRenderer({
  toolName: "execute_sql",
  target: "arguments",
  decide: (ctx) => ({
    action: "render",
    node: createElement("pre", { className: "text-xs" }, String(ctx.arguments.sql ?? "")),
  }),
});
```

### Composer References ("@" Mentions & Chips)

Plugins can attach structured entity references to user messages. A reference is rendered as an atomic chip (`@[label]`) in the chat composer; on submit, references are serialized into a hidden `COMPOSER_REFERENCES_V1` JSON payload appended after the visible question text (same pattern as `WIDGET_MAKE_CHOICES_ANSWERS`). The UI strips the payload when rendering user messages, but it persists in message content, so retry and history replay keep it.

The reference contract (`ComposerReference`, re-exported from `@/plugins/registry`):

| Field | Type | Description |
|---|---|---|
| `kind` | `string` | Reference kind, e.g. `"document"`. |
| `id` | `string` | Stable identifier of the referenced entity (e.g. document UUID). This is the only lookup key. |
| `label` | `string` | Human-readable chip label; display-only, never used as a key. |
| `sourcePluginId` | `string?` | Plugin that produced the reference. |

There are three integration points:

1. **`addComposerReference(reference)`** — available in `ResultRenderContext` for `sdk.results()` / `sdk.widget()` renderers. Lets a widget action (e.g. an "Add to question" button on a result card) attach a chip to the composer without submitting a message.

2. **`sdk.referenceSuggestions(fetchSuggestions, options?)`** — registers a provider for the composer's `@` mention autocomplete. `fetchSuggestions(query, signal)` returns `ReferenceSuggestion[]` (`{ reference, description? }`); an empty query means "show recent/default entries", and implementations should honour the `AbortSignal`. Providers from all plugins are merged in `priority` order (lower first, default `100`) and deduplicated by reference identity. The composer only enables the `@` mention UI (and advertises it in the placeholder) when at least one provider is registered.

3. **`sdk.conversationReferences(widgetType, extract)`** — registers an extractor that maps a rendered widget payload (e.g. source cards) to the references it displays. The mention popover uses this to prioritise entities already shown in the current conversation over the full corpus.

**Scoping to one agent:** the suggestion registry is global, so a plugin whose references only make sense for its own agent should register the provider from a headless component mounted via an agent-gated slot, and unregister on unmount:

```typescript
import { useEffect } from "react";
import { createPluginSDK } from "@/plugins/sdk";

const PLUGIN_ID = "my_plugin";

function ReferenceProviderMount(): null {
  useEffect(() => {
    registerMyReferenceProvider();   // sdk.referenceSuggestions + sdk.conversationReferences
    return () => unregisterMyReferenceProvider();
  }, []);
  return null;
}

export function registerPlugin(): void {
  const sdk = createPluginSDK(PLUGIN_ID);
  sdk.slot("detail.panel", ReferenceProviderMount, {
    condition: (ctx) => ctx.agentId === PLUGIN_ID,
  });
}
```

**Backend side:** the plugin's prompt should instruct the agent to parse the `COMPOSER_REFERENCES_V1` payload from the user message and resolve each reference by its `id` through a retrieval tool (e.g. `document_get(document_id=<uuid>)`). Treat `label` as untrusted display text — never use it as a lookup key. See the search plugin (`plugins/search/`) for a complete reference implementation.


### Core Widget Toolkit Contract (`_widget_type`)

If you want to use a reusable core widget (without custom React rendering), return rows with:

- `_widget_type` - widget ID registered in core
- `_widget_payload` - widget-specific data

When multiple successful tools appear in one response, frontend extraction prefers the latest successful payload that contains widget metadata. This keeps interactive widgets (like choices flows) visible even if a later non-widget tool also succeeds.

Example payload for `make_choices`:

```json
[
  {
    "_widget_type": "make_choices",
    "_widget_payload": {
      "questions": [
        {
          "id": "question_1",
          "prompt": "Jakie kryterium jest dla Ciebie najważniejsze?",
          "allow_multiple": true,
          "allow_open_text": true,
          "open_text_placeholder": "Wpisz własną odpowiedź",
          "options": [
            {"id": "option_1", "label": "Opcja 1"},
            {"id": "option_2", "label": "Opcja 2"},
            {"id": "option_3", "label": "Opcja 3"}
          ]
        }
      ]
    }
  }
]
```

Notes for plugin authors:

- Keep business logic in plugin (when and why a widget is shown).
- Keep payload domain-specific in plugin (`_widget_payload`).
- Core only provides generic rendering and action dispatch.
- For interactive core widgets (for example `make_choices`), submitted answers are sent as a structured JSON block in a new user message. Multi-select values are preserved as arrays, while chat UI can display only the human-readable segment.
- If `_widget_type` is unknown, UI safely falls back to default results table.
- Widget renderers registered through `sdk.widget(...)` are private to the plugin by default.
- Private widget ownership is resolved from `sourcePluginId` (message source), with `agentId` as legacy fallback.
- To expose a widget type globally, declare it in plugin manifest:
  - `frontend.public_widgets: ["your_widget_type"]`

---

## Example

See the `plugins/` directory (sibling to `core/`) in your project for example implementations.
