# Authentication

recordya-chat supports two authentication modes, controlled by a single environment variable:

| Mode | `AUTH_MODE` | Description |
|------|-------------|-------------|
| **Keycloak (SSO)** | `keycloak` | OpenID Connect via Keycloak. Passwords live in Keycloak, users are auto-provisioned in app DB on first login. **Default.** |
| **Local** | `local` | Email + password stored in app DB (`users.hashed_password`). No external IdP needed. |

## Switching Modes

1. Set `AUTH_MODE` in root `.env`:
   ```bash
   AUTH_MODE=keycloak   # SSO (default)
   AUTH_MODE=local      # standalone email/password
   ```
2. Restart backend (`docker compose restart backend` or re-run uvicorn).
3. Refresh the browser — frontend fetches auth config from `/auth/config` on load.

No code changes or redeployment needed. Both modes use JWT Bearer tokens for API calls — the difference is only in how the token is obtained.

## Mode: Keycloak (SSO)

### How It Works

1. Frontend loads → fetches `/auth/config` → gets `auth_mode: "keycloak"` + Keycloak URLs
2. User opens app → auto-redirects to Keycloak login page (OIDC Authorization Code + PKCE)
3. User authenticates in Keycloak → redirected back to `/auth/callback`
4. Frontend exchanges code for tokens via `oidc-client-ts`
5. Frontend calls `/auth/me` with Keycloak access token
6. Backend validates token (RS256 via JWKS), extracts email + roles
7. **JIT provisioning**: if user doesn't exist in app DB, a record is created automatically
8. Role and display name are **synced from Keycloak on every login**

### Keycloak Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_MODE` | `keycloak` | Must be `keycloak` |
| `KEYCLOAK_URL` | `http://localhost:8180` | Internal URL (backend → Keycloak, e.g. `http://keycloak:8080` in Docker) |
| `KEYCLOAK_FRONTEND_URL` | falls back to `KEYCLOAK_URL` | Public URL (browser → Keycloak, e.g. `http://localhost:8180`) |
| `KEYCLOAK_REALM` | `recordya` | Keycloak realm name |
| `KEYCLOAK_CLIENT_ID` | `recordya-chat` | OIDC client ID |
| `KEYCLOAK_DB_PASSWORD` | `keycloak` | Password for Keycloak's own PostgreSQL |
| `KEYCLOAK_ADMIN` | `admin` | Keycloak admin console username |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Keycloak admin console password |

### Managing Users (Keycloak Mode)

**Keycloak is the single source of truth for users and roles.**

#### Keycloak Admin Panel

URL: `http://localhost:8180/admin` (login: `admin` / `admin`)

- **Create user**: Users → Add user → set email, first/last name → Credentials tab → set password
- **Assign role**: Users → select user → Role mapping → Assign role → select `super_admin`, `admin`, or `user` (`super_admin` additionally unlocks the agent reasoning panel)
- **Delete user**: Users → select user → Delete

#### Keycloak Admin API

```bash
# Get admin token
ADMIN_TOKEN=$(curl -sf -X POST "http://localhost:8180/realms/master/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=admin-cli&username=admin&password=admin" \
  -H "Content-Type: application/x-www-form-urlencoded" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Create user
curl -sf -X POST "http://localhost:8180/admin/realms/recordya/users" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jan@firma.pl",
    "username": "jan@firma.pl",
    "emailVerified": true,
    "enabled": true,
    "credentials": [{"type": "password", "value": "haslo123", "temporary": false}]
  }'
```

#### Role Mapping

Keycloak realm roles map to app roles:

| Keycloak realm role | App `users.role` | Effect |
|---------------------|------------------|--------|
| `super_admin` | `super_admin` | All admin powers, plus sees the agent reasoning panel and full tool call data over SSE / in chat history |
| `admin` | `admin` | No rate limits, full administrative access (user management, plugin admin endpoints), but the reasoning panel and full tool call data are redacted |
| _(any other / none)_ | `user` | Standard rate-limited access; SSE events are redacted (no tool ids/arguments/results) and `reasoning_steps` are stripped from chat history responses |

`super_admin` is a superset of `admin` (it satisfies every `admin`-gated check). Roles sync automatically on every login. No need to update app DB manually.

> **Data visibility:** the reasoning gate is enforced at three layers — `POST /api/agent/stream` (SSE event redaction), `POST /api/chats/{id}/messages` (only `super_admin` can persist `reasoning_steps`), and `GET /api/chats/{id}/messages` (returns `reasoning_steps: null` for everyone except `super_admin`). See [`docs/architecture.md` — Role-Based SSE Redaction](architecture.md#role-based-sse-redaction).

### Realm Seed (`realm-export.json`)

`keycloak/realm-export.json` is imported on first Keycloak start (empty volume). It contains:

- Realm `recordya` with `super_admin`, `admin`, and `user` roles
- OIDC client `recordya-chat` (PKCE, correct redirect URIs)
- Realm role mapper (so roles appear in JWT `realm_roles` claim)
- Seed user `admin@test.com` / `admin123` with `super_admin`, `admin`, and `user` roles

> ⚠️ **Development only.** The seed user `admin@test.com` / `admin123` (and the
> Keycloak admin `admin` / `admin`) exist purely to make a fresh local checkout
> runnable out of the box. **Before any non-local deployment**, remove or disable
> this user in `realm-export.json` (or rotate its password in the Keycloak admin
> console) and change `KEYCLOAK_ADMIN_PASSWORD`. Never ship these credentials to
> a shared or production environment.

### Login Page Theme

Custom Keycloak theme in `keycloak/themes/recordya/login/` renders a login page matching the app's design (Inter font, shadcn/ui-style card). The theme uses a standalone FreeMarker template (`login.ftl`) with inline CSS — no dependency on PatternFly.

## Mode: Local

### How It Works

1. Frontend loads → fetches `/auth/config` → gets `auth_mode: "local"`
2. User sees email/password form (same design as Keycloak theme)
3. Frontend POSTs to `/auth/login` → backend verifies bcrypt hash → returns JWT
4. Frontend stores token in `localStorage`, sends as `Authorization: Bearer` header

### Local Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_MODE` | `keycloak` | Must be `local` |
| `SECRET_KEY` | _(required)_ | HMAC key for JWT signing (HS256). Min 32 chars. |
| `ACCESS_TOKEN_EXPIRE_HOURS` | `24` | JWT lifetime |

### Managing Users (Local Mode)

```bash
# Register via API
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "securepassword123"}'

# Or use the setup script
./scripts/create-user.sh
```

Users created in Keycloak mode (JIT provisioned) have empty `hashed_password` and **cannot log in** in local mode. This is by design — each mode manages its own credentials independently.

## Session Lifecycle (Frontend)

The frontend funnels every authenticated HTTP call through a single wrapper that participates in a shared session-expiry flow. This keeps token refresh, logout, and cross-tab synchronization consistent across core and plugin code.

### `authFetch` — the only HTTP entry point

All authenticated requests (core API + plugin endpoints + SSE streams) go through `authFetch` (`core/frontend/src/lib/api.ts`). It:

1. Injects the `Authorization: Bearer <token>` header.
2. On `401`, runs a **single-flight** silent token refresh (Keycloak mode) and retries the request once.
3. If the refresh fails — or the retry still returns `401` — calls `forceLogout('expired')`.
4. Skips the whole flow for public endpoints whitelisted in `auth-session.ts` (`/auth/config`, `/auth/login`, `/auth/register`).

The thin `request<T>()` helper (used by core) and plugin-level helpers (e.g. a plugin's own `myPluginRequest`, etc.) are all built on top of `authFetch`. **Plugins must not call `fetch()` directly with an `Authorization` header** — use `authFetch` so they participate in the global session lifecycle.

> Caveat: `authFetch` retries on `401` by re-sending `init.body`. If the body is non-replayable (e.g. a `ReadableStream` or already-consumed `FormData`), the retry will fail. JSON bodies and `URLSearchParams` are fine.

### `auth-session.ts` — the React-free coordination layer

`core/frontend/src/lib/auth-session.ts` owns the cross-cutting session state and is intentionally free of React imports so it can be used from the HTTP layer. It exposes:

- `tryRefreshSession()` — single-flight silent refresh (deduped via a shared promise).
- `forceLogout(reason)` — drop local credentials, dispatch the `auth:expired` window event, and broadcast to other tabs.
- `broadcastLogout()` — write a fresh timestamp to a dedicated `localStorage` key so sibling tabs receive a `storage` event.
- `onAuthExpired(callback)` — subscribe to the `auth:expired` event (used by `useAuth`).

### React integration (`useAuth`)

`useAuth` (`core/frontend/src/hooks/useAuth.ts`) subscribes to `auth:expired` once on mount. When the event fires it clears the React-Query cache, sets `isAuthenticated=false` (which causes the protected routes to redirect to `/auth`) and — for the `cross-tab` reason — marks a `sessionStorage` flag so the login screen suppresses its auto-SSO redirect. It also wires `subscribeKeycloakExpiry()` so OIDC events (`addAccessTokenExpired`, `addSilentRenewError`, `addUserSignedOut`) flow through the same `forceLogout('expired')` path.

### Cross-tab logout

When the user logs out (or `forceLogout` fires) in Tab A:

1. Tab A calls `broadcastLogout()` → writes `auth:logout:broadcast` in `localStorage`.
2. Tab B/C/... receive a `storage` event and run the same cleanup with `reason: 'cross-tab'`.
3. `useAuth` in sibling tabs sets a `sessionStorage` flag (`auth:cross-tab-logout`) and flips to the logged-out state.
4. The router takes sibling tabs to `/auth`. The login screen reads the flag and — instead of auto-SSO-redirecting — renders a dedicated card ("Wylogowano w innej karcie") with a manual "Zaloguj się ponownie" button.

This manual gate eliminates an SSO race condition where sibling tabs would otherwise try to re-enter the Keycloak flow while Tab A was still tearing down the Keycloak session, leaving one tab stuck on `/auth/callback`.

### `/auth/callback` fallback

`AuthCallback.tsx` watches the `useAuth` state and, if the callback resolves with `isLoading=false && !isAuthenticated`, navigates to `/auth` instead of leaving the user on a spinner. This is a safety net for any callback failure (e.g. an invalidated OIDC `code` after a sibling-tab logout).

### User-facing feedback

There is no destructive toast on session expiry. The redirect to the login screen is the feedback. For the cross-tab case the dedicated relogin card carries the message — full-screen, deliberate, dismissed only by user action.

## Architecture Notes

- **App DB `users` table is always required** — chats, messages, daily usage, and rate limiting all reference `users.id` via foreign keys
- **Token validation**: Keycloak mode uses RS256 (JWKS from Keycloak), local mode uses HS256 (symmetric `SECRET_KEY`)
- **`/auth/config` endpoint** is public (no auth required) — frontend calls it at bootstrap to determine which login flow to show
- **Audience/`azp` validation**: Keycloak tokens often carry `aud: "account"` by default, so the backend accepts the token when **either** the `aud` claim contains the configured client ID **or** the `azp` (authorized party) claim equals it

