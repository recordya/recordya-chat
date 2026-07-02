/**
 * Application configuration.
 * Loaded at runtime from /config/config.json so the backend URL
 * can be changed without rebuilding the frontend (e.g. via K8s ConfigMap).
 *
 * Auth config is fetched from backend /auth/config to stay in sync
 * with the backend AUTH_MODE setting (single source of truth).
 */

interface AppConfig {
  apiUrl: string;
  showBranding?: boolean;
}

interface AuthConfig {
  authMode: 'keycloak' | 'local';
  locale?: string;
  keycloakUrl?: string;
  keycloakRealm?: string;
  keycloakClientId?: string;
}

const DEFAULT_CONFIG: AppConfig = {
  apiUrl: 'http://localhost:8000',
  showBranding: false,
};

const DEFAULT_AUTH_CONFIG: AuthConfig = {
  authMode: 'local',
  locale: 'en',
};

let _config: AppConfig = { ...DEFAULT_CONFIG };
let _authConfig: AuthConfig = { ...DEFAULT_AUTH_CONFIG };

/**
 * Load configuration from /config/config.json and backend /auth/config.
 * Must be called once before the app renders (see main.tsx).
 */
export async function loadConfig(): Promise<void> {
  // 1. Load static frontend config
  try {
    const response = await fetch('/config/config.json');
    if (response.ok) {
      _config = await response.json();
    } else {
      console.warn('Failed to load config.json, using defaults');
    }
  } catch {
    console.warn('Could not fetch config.json, using defaults');
  }

  // 2. Fetch auth config from backend
  try {
    const response = await fetch(`${_config.apiUrl}/auth/config`);
    if (response.ok) {
      const data = await response.json();
      _authConfig = {
        authMode: data.auth_mode,
        locale: data.locale,
        keycloakUrl: data.keycloak_url,
        keycloakRealm: data.keycloak_realm,
        keycloakClientId: data.keycloak_client_id,
      };
    } else {
      console.warn('Failed to load auth config from backend, using defaults');
    }
  } catch {
    console.warn('Could not fetch auth config, using defaults');
  }
}

/**
 * Backend API base URL.
 */
export function getApiUrl(): string {
  return _config.apiUrl;
}

export function getShowBranding(): boolean {
  return _config.showBranding ?? false;
}

export function getAuthConfig(): AuthConfig {
  return _authConfig;
}

/**
 * Static UI locale resolved from the backend (single source of truth).
 * Falls back to 'en' when unset or unknown.
 */
export function getLocale(): string {
  return _authConfig.locale || 'en';
}

