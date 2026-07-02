import { useState, useEffect, useCallback, useRef } from "react";
import {
  login as apiLogin,
  logout as apiLogout,
  getCurrentUser,
  getToken,
  clearToken,
  ApiError,
  type UserResponse,
} from "@/lib/api";
import { getAuthConfig } from "@/lib/config";
import {
  keycloakGetUser,
  keycloakLogin,
  keycloakLogout,
  keycloakHandleCallback,
  subscribeKeycloakExpiry,
} from "@/lib/auth-keycloak";
import {
  broadcastLogout,
  forceLogout,
  markCrossTabLogout,
  onAuthExpired,
} from "@/lib/auth-session";
import { queryClient } from "@/lib/queryClient";
import i18n from "@/i18n";

export interface AuthState {
  user: UserResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

function isKeycloakMode(): boolean {
  return getAuthConfig().authMode === "keycloak";
}

export function useAuth() {
  const [authState, setAuthState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
  });

  // Check authentication status on mount
  useEffect(() => {
    const checkAuth = async () => {
      if (isKeycloakMode()) {
        await checkKeycloakAuth();
      } else {
        await checkLocalAuth();
      }
    };

    const checkLocalAuth = async () => {
      const token = getToken();
      if (!token) {
        setAuthState({ user: null, isLoading: false, isAuthenticated: false });
        return;
      }

      try {
        const user = await getCurrentUser();
        setAuthState({ user, isLoading: false, isAuthenticated: true });
      } catch {
        clearToken();
        setAuthState({ user: null, isLoading: false, isAuthenticated: false });
      }
    };

    const checkKeycloakAuth = async () => {
      // Handle OIDC callback if we're on the callback URL
      if (window.location.pathname === "/auth/callback") {
        try {
          await keycloakHandleCallback();
          // Redirect to home after successful callback
          window.location.replace("/");
          return;
        } catch (error) {
          console.error("Keycloak callback failed:", error);
          setAuthState({ user: null, isLoading: false, isAuthenticated: false });
          return;
        }
      }

      // Check if we have a valid Keycloak session
      const kcUser = await keycloakGetUser();
      if (!kcUser || kcUser.expired) {
        setAuthState({ user: null, isLoading: false, isAuthenticated: false });
        return;
      }

      // Fetch user info from our backend (triggers JIT provisioning)
      try {
        const user = await getCurrentUser();
        setAuthState({ user, isLoading: false, isAuthenticated: true });
      } catch {
        setAuthState({ user: null, isLoading: false, isAuthenticated: false });
      }
    };

    checkAuth();
  }, []);

  // Track current auth state in a ref so the session-expiry listener
  // can be installed once without resubscribing on every state change.
  const isAuthenticatedRef = useRef(authState.isAuthenticated);
  useEffect(() => {
    isAuthenticatedRef.current = authState.isAuthenticated;
  }, [authState.isAuthenticated]);

  // Listen for global session-expiry events fired by the HTTP layer
  // (api.ts -> auth-session.ts) and by OIDC token lifecycle events.
  useEffect(() => {
    const unsubscribeAuthExpired = onAuthExpired(({ reason }) => {
      if (!isAuthenticatedRef.current) return;
      queryClient.clear();
      // Cross-tab logout: mark the session so the login screen
      // suppresses its auto-SSO redirect and the user re-enters
      // through a deliberate click — avoiding the SSO race with
      // the tab that originated the logout. The dedicated login
      // screen carries the user-facing message, so no toast is
      // needed (and no toast at all on regular session expiry —
      // the redirect to the login screen is the feedback).
      if (reason === "cross-tab") {
        markCrossTabLogout();
      }
      setAuthState({ user: null, isLoading: false, isAuthenticated: false });
    });

    let unsubscribeKeycloak: (() => void) | undefined;
    if (isKeycloakMode()) {
      unsubscribeKeycloak = subscribeKeycloakExpiry(() => forceLogout("expired"));
    }

    return () => {
      unsubscribeAuthExpired();
      unsubscribeKeycloak?.();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    if (isKeycloakMode()) {
      // In Keycloak mode, redirect to Keycloak login
      await keycloakLogin();
      return { data: null, error: null };
    }

    try {
      await apiLogin({ email, password });
      const user = await getCurrentUser();
      setAuthState({ user, isLoading: false, isAuthenticated: true });
      return { data: { user }, error: null };
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Login failed";
      return { data: null, error: { message } };
    }
  }, []);

  const signOut = useCallback(async () => {
    queryClient.clear();
    // Notify sibling tabs first so they tear down their own session
    // state before this tab navigates away (Keycloak top-level redirect).
    broadcastLogout();

    if (isKeycloakMode()) {
      setAuthState({ user: null, isLoading: false, isAuthenticated: false });
      await keycloakLogout();
      return { error: null };
    }

    apiLogout();
    setAuthState({ user: null, isLoading: false, isAuthenticated: false });
    return { error: null };
  }, []);

  const getDisplayName = useCallback(() => {
    if (!authState.user) return null;
    return authState.user.display_name || authState.user.email?.split("@")[0] || i18n.t("common:userFallback");
  }, [authState.user]);

  const refreshUser = useCallback(async () => {
    try {
      const user = await getCurrentUser();
      setAuthState((prev) => ({ ...prev, user, isAuthenticated: true }));
      return user;
    } catch {
      return null;
    }
  }, []);

  return {
    user: authState.user,
    isLoading: authState.isLoading,
    isAuthenticated: authState.isAuthenticated,
    session: authState.user ? { user: authState.user } : null,
    signIn,
    signOut,
    getDisplayName,
    refreshUser,
  };
}
