/**
 * Keycloak OIDC client using oidc-client-ts.
 * Handles Authorization Code + PKCE flow for SPA.
 */

import { UserManager, User, WebStorageStateStore } from 'oidc-client-ts';
import { getAuthConfig } from './config';

let _userManager: UserManager | null = null;

function getUserManager(): UserManager {
  if (_userManager) return _userManager;

  const authConfig = getAuthConfig();
  if (authConfig.authMode !== 'keycloak') {
    throw new Error('Keycloak auth not configured');
  }

  const authority = `${authConfig.keycloakUrl}/realms/${authConfig.keycloakRealm}`;

  _userManager = new UserManager({
    authority,
    client_id: authConfig.keycloakClientId!,
    redirect_uri: `${window.location.origin}/auth/callback`,
    post_logout_redirect_uri: window.location.origin,
    response_type: 'code',
    scope: 'openid email profile',
    automaticSilentRenew: true,
    userStore: new WebStorageStateStore({ store: sessionStorage }),
  });

  return _userManager;
}

/**
 * Redirect to Keycloak login page.
 */
export async function keycloakLogin(): Promise<void> {
  const mgr = getUserManager();
  await mgr.signinRedirect();
}

/**
 * Handle the OIDC callback after Keycloak redirects back.
 * Returns the authenticated user.
 */
export async function keycloakHandleCallback(): Promise<User> {
  const mgr = getUserManager();
  return mgr.signinRedirectCallback();
}

/**
 * Get the current OIDC user (from session storage).
 * Returns null if not logged in.
 */
export async function keycloakGetUser(): Promise<User | null> {
  const mgr = getUserManager();
  return mgr.getUser();
}

/**
 * Get a valid access token. Refreshes automatically if needed.
 */
export async function keycloakGetAccessToken(): Promise<string | null> {
  const user = await keycloakGetUser();
  if (!user || user.expired) return null;
  return user.access_token;
}

/**
 * Logout from Keycloak (redirects to Keycloak logout page).
 */
export async function keycloakLogout(): Promise<void> {
  const mgr = getUserManager();
  await mgr.signoutRedirect();
}

/**
 * Force a silent token refresh via the OIDC `signinSilent` flow.
 * Used by the 401 handler to recover from an expired access token
 * without redirecting the user.
 */
export async function keycloakSilentRefresh(): Promise<User | null> {
  const mgr = getUserManager();
  return mgr.signinSilent();
}

/**
 * Drop the cached OIDC user from `sessionStorage` without contacting
 * Keycloak. Used when the session has already expired server-side and
 * we just need the local app to forget it.
 */
export async function keycloakClearLocalSession(): Promise<void> {
  const mgr = getUserManager();
  await mgr.removeUser();
}

export type KeycloakExpiryListener = () => void;

/**
 * Subscribe to events that indicate the OIDC session is no longer
 * usable (token expired, silent renew failed, back-channel signout).
 * Returns an unsubscribe function.
 */
export function subscribeKeycloakExpiry(
  listener: KeycloakExpiryListener,
): () => void {
  const mgr = getUserManager();
  const onExpired = (): void => listener();
  const onSilentRenewError = (): void => listener();
  const onUserSignedOut = (): void => listener();
  mgr.events.addAccessTokenExpired(onExpired);
  mgr.events.addSilentRenewError(onSilentRenewError);
  mgr.events.addUserSignedOut(onUserSignedOut);
  return () => {
    mgr.events.removeAccessTokenExpired(onExpired);
    mgr.events.removeSilentRenewError(onSilentRenewError);
    mgr.events.removeUserSignedOut(onUserSignedOut);
  };
}
