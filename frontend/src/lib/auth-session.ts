/**
 * Shared session-expiry plumbing for the HTTP layer.
 *
 * - Single-flight token refresh so a burst of concurrent 401s triggers
 *   exactly one refresh attempt.
 * - `forceLogout()` clears any locally stored credentials and emits
 *   the `auth:expired` window event so React (useAuth) can flip the
 *   app into the logged-out state, clear caches and notify the user.
 *
 * This module is React-free on purpose: it is imported by `api.ts`
 * (and later by plugins via `authFetch`), so it must stay usable from
 * outside the component tree.
 */

import { getAuthConfig } from './config';
import { keycloakClearLocalSession, keycloakSilentRefresh } from './auth-keycloak';

export const AUTH_EXPIRED_EVENT = 'auth:expired';

export type AuthExpiredReason = 'expired' | 'invalid' | 'manual' | 'cross-tab';

export interface AuthExpiredDetail {
  reason: AuthExpiredReason;
}

/**
 * Endpoints that must never trigger the auto-logout flow on 401.
 * Login/registration have their own UX, `/auth/config` is public.
 */
const AUTH_WHITELIST: readonly string[] = [
  '/auth/config',
  '/auth/login',
  '/auth/register',
];

const LOCAL_TOKEN_KEY = 'access_token';

/**
 * Cross-tab broadcast channel: writing to this `localStorage` key
 * fires a `storage` event in every *other* tab on the same origin,
 * which the listener below uses to mirror the logout cleanup.
 */
const LOGOUT_BROADCAST_KEY = 'auth:logout:broadcast';

let refreshPromise: Promise<boolean> | null = null;
let loggingOut = false;

export function isAuthWhitelisted(endpoint: string): boolean {
  const path = endpoint.startsWith('http')
    ? new URL(endpoint).pathname
    : endpoint.split('?')[0];
  return AUTH_WHITELIST.some((entry) => path === entry);
}

/**
 * Attempt to refresh the current session. Concurrent callers share
 * the same in-flight promise.
 *
 * Returns `true` if a fresh access token is now available, `false`
 * otherwise (e.g. local-JWT mode has no refresh endpoint).
 */
export function tryRefreshSession(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = doRefresh().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

async function doRefresh(): Promise<boolean> {
  if (getAuthConfig().authMode !== 'keycloak') {
    // Local JWT mode has no refresh path.
    return false;
  }
  try {
    const user = await keycloakSilentRefresh();
    return Boolean(user && !user.expired);
  } catch {
    return false;
  }
}

function performLogoutCleanup(reason: AuthExpiredReason): void {
  if (loggingOut) return;
  loggingOut = true;
  try {
    localStorage.removeItem(LOCAL_TOKEN_KEY);
  } catch {
    // Storage may be unavailable (private mode, SSR); ignore.
  }
  if (getAuthConfig().authMode === 'keycloak') {
    void keycloakClearLocalSession().catch(() => {
      // Best-effort: even if the OIDC store cleanup fails we still
      // want to surface the expired state to the UI.
    });
  }
  try {
    window.dispatchEvent(
      new CustomEvent<AuthExpiredDetail>(AUTH_EXPIRED_EVENT, {
        detail: { reason },
      }),
    );
  } finally {
    // Reset on the next macrotask so a fresh login can later
    // re-trigger this flow without leaking the dedupe flag.
    setTimeout(() => {
      loggingOut = false;
    }, 0);
  }
}

/**
 * Notify other tabs on the same origin that the session has ended.
 * Writing a fresh timestamp guarantees the `storage` event fires even
 * if the previous value was identical.
 */
export function broadcastLogout(): void {
  try {
    localStorage.setItem(LOGOUT_BROADCAST_KEY, String(Date.now()));
  } catch {
    // No-op — cross-tab sync is best effort.
  }
}

/**
 * Drop any locally cached credentials, emit `auth:expired` and notify
 * sibling tabs so the whole browser falls back to the logged-out
 * state in lockstep. Idempotent within a single logout burst.
 */
export function forceLogout(reason: AuthExpiredReason = 'expired'): void {
  performLogoutCleanup(reason);
  broadcastLogout();
}

// Install the cross-tab logout listener exactly once at module load.
// A `storage` event only fires in tabs *other* than the writer, so
// this never loops back into the originating tab.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('storage', (event: StorageEvent) => {
    if (event.key !== LOGOUT_BROADCAST_KEY) return;
    if (!event.newValue) return;
    performLogoutCleanup('cross-tab');
  });
}

/**
 * `sessionStorage` flag set when this tab was logged out as a result
 * of another tab broadcasting a logout. The login screen reads it to
 * suppress its auto-SSO redirect so the user has to click "Zaloguj
 * się ponownie" manually — this eliminates the race where two tabs
 * round-trip through Keycloak at the same time and leave one tab
 * stuck on `/auth/callback`.
 */
const CROSS_TAB_LOGOUT_FLAG = 'auth:cross-tab-logout';

export function markCrossTabLogout(): void {
  try {
    sessionStorage.setItem(CROSS_TAB_LOGOUT_FLAG, '1');
  } catch {
    // sessionStorage may be unavailable (private mode, SSR); ignore.
  }
}

export function consumeCrossTabLogoutFlag(): boolean {
  try {
    const value = sessionStorage.getItem(CROSS_TAB_LOGOUT_FLAG);
    if (value === null) return false;
    sessionStorage.removeItem(CROSS_TAB_LOGOUT_FLAG);
    return true;
  } catch {
    return false;
  }
}

/**
 * Subscribe to session-expiry notifications. Returns an unsubscribe
 * function suitable for `useEffect` cleanup.
 */
export function onAuthExpired(
  callback: (detail: AuthExpiredDetail) => void,
): () => void {
  const listener = (event: Event): void => {
    const custom = event as CustomEvent<AuthExpiredDetail>;
    callback(custom.detail ?? { reason: 'expired' });
  };
  window.addEventListener(AUTH_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
}

/**
 * Test-only: reset the module-level state between specs.
 */
export function __resetAuthSessionForTests(): void {
  refreshPromise = null;
  loggingOut = false;
}
