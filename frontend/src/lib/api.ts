/**
 * API client for the FastAPI backend.
 * Handles authentication and API calls with JWT tokens.
 * Supports both local (email/password) and Keycloak (OIDC) auth modes.
 */

import { getApiUrl, getAuthConfig } from './config';
import { keycloakGetAccessToken } from './auth-keycloak';
import {
  forceLogout,
  isAuthWhitelisted,
  tryRefreshSession,
} from './auth-session';

// Token storage key (used in local auth mode)
const TOKEN_KEY = 'access_token';

/**
 * Get stored access token (local mode).
 */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Store access token (local mode).
 */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

/**
 * Remove stored access token (local mode).
 */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Get the current access token from the appropriate source.
 */
export async function getAccessToken(): Promise<string | null> {
  if (getAuthConfig().authMode === 'keycloak') {
    return keycloakGetAccessToken();
  }
  return getToken();
}

/**
 * API error class.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public data?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface AuthFetchOptions extends RequestInit {
  /** Skip Authorization header and 401 handling (for public endpoints). */
  skipAuth?: boolean;
}

function resolveUrl(input: string): string {
  return input.startsWith('http') ? input : `${getApiUrl()}${input}`;
}

async function applyAuthHeader(
  headers: HeadersInit | undefined,
): Promise<Headers> {
  const merged = new Headers(headers);
  const token = await getAccessToken();
  if (token) merged.set('Authorization', `Bearer ${token}`);
  return merged;
}

/**
 * Authenticated `fetch` with shared 401 handling.
 *
 * On 401 the request is retried once after a silent token refresh
 * (Keycloak mode). If the refresh fails or the retry still returns
 * 401, the global `forceLogout` flow is triggered and the original
 * response is returned to the caller for normal error handling.
 *
 * Note: callers that pass a non-replayable body (e.g. `ReadableStream`,
 * single-use `FormData`) must handle their own retry logic.
 */
export async function authFetch(
  input: string,
  init: AuthFetchOptions = {},
): Promise<Response> {
  const { skipAuth, headers, ...rest } = init;
  const url = resolveUrl(input);
  const skip = skipAuth || isAuthWhitelisted(input);

  if (skip) {
    return fetch(url, { ...rest, headers: new Headers(headers) });
  }

  let response = await fetch(url, {
    ...rest,
    headers: await applyAuthHeader(headers),
  });

  if (response.status !== 401) return response;

  const refreshed = await tryRefreshSession();
  if (!refreshed) {
    forceLogout('expired');
    return response;
  }

  response = await fetch(url, {
    ...rest,
    headers: await applyAuthHeader(headers),
  });
  if (response.status === 401) {
    forceLogout('expired');
  }
  return response;
}

/**
 * Make a JSON API request with authentication.
 *
 * Thin wrapper over `authFetch` that sets `Content-Type: application/json`,
 * parses the JSON body and throws `ApiError` on non-2xx responses.
 */
export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  const response = await authFetch(endpoint, { ...options, headers });
  const data = await response.json();

  if (!response.ok) {
    throw new ApiError(
      data.detail || data.error || 'Request failed',
      response.status,
      data
    );
  }

  return data;
}

// ============= Auth API =============

export interface RegisterRequest {
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  user_id: string;
  email: string;
  role: string;
  display_name?: string | null;
  enabled?: boolean;
}

export interface UsageResponse {
  remaining: number;
  limit: number;
  is_admin: boolean;
  is_super_admin: boolean;
  chat_restricted: boolean;
}

/**
 * Register a new user account.
 */
export async function register(data: RegisterRequest): Promise<UserResponse> {
  return request<UserResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * Login and get access token.
 */
export async function login(data: LoginRequest): Promise<TokenResponse> {
  const response = await request<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(data),
  });

  // Store the token
  setToken(response.access_token);

  return response;
}

/**
 * Logout - clear stored token.
 */
export function logout(): void {
  clearToken();
}

/**
 * Get current user information.
 */
export async function getCurrentUser(): Promise<UserResponse> {
  return request<UserResponse>('/auth/me');
}

export interface UpdateProfileRequest {
  display_name?: string | null;
}

/**
 * Update current user profile (display name).
 */
export async function updateProfile(data: UpdateProfileRequest): Promise<UserResponse> {
  return request<UserResponse>('/auth/me', {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

/**
 * List all users (admin only).
 */
export async function listUsers(): Promise<UserResponse[]> {
  return request<UserResponse[]>('/auth/users');
}

export interface CreateUserRequest {
  email: string;
  display_name?: string | null;
  plugin_data?: Record<string, unknown>;
}

/**
 * Create a new user (admin only). In Keycloak mode also provisions the
 * Keycloak account and sends a set-password email to the user.
 */
export async function createUser(data: CreateUserRequest): Promise<UserResponse> {
  return request<UserResponse>('/auth/users', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * Deactivate a user (admin only).
 */
export async function deactivateUser(userId: string): Promise<UserResponse> {
  return request<UserResponse>(`/auth/users/${userId}/deactivate`, {
    method: 'POST',
  });
}

/**
 * Re-activate a user (admin only).
 */
export async function activateUser(userId: string): Promise<UserResponse> {
  return request<UserResponse>(`/auth/users/${userId}/activate`, {
    method: 'POST',
  });
}

/**
 * Get usage statistics.
 */
export async function getUsage(): Promise<UsageResponse> {
  return request<UsageResponse>('/auth/usage');
}

// ============= Model Config API =============

export interface ModelOption {
  id: string;
  name: string;
}

export interface ModelConfig {
  available: ModelOption[];
  selected: string;
}

/**
 * Get the available LLM models and the active selection.
 */
export async function getModelConfig(): Promise<ModelConfig> {
  return request<ModelConfig>('/api/config/models');
}

/**
 * Change the active LLM model (admin only).
 */
export async function updateModelConfig(model: string): Promise<ModelConfig> {
  return request<ModelConfig>('/api/config/models', {
    method: 'PATCH',
    body: JSON.stringify({ model }),
  });
}

// ============= Chat API =============

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

// ============= Chats API =============

export interface ChatResponse {
  id: string;
  title: string | null;
  datasource: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessageResponse {
  id: string;
  role: string;
  content: string;
  sql_query: string | null;
  results_json: string | null;
  tool_results: Record<string, unknown>[] | null;
  reasoning_steps: Record<string, unknown>[] | null;
  langfuse_trace_id: string | null;
  feedback: ChatMessageFeedbackResponse | null;
  created_at: string;
}

export type MessageFeedbackRating = 'positive' | 'negative';

export interface ChatMessageFeedbackResponse {
  id: string;
  message_id: string;
  chat_id: string;
  rating: MessageFeedbackRating;
  saved_time: string | null;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateChatRequest {
  title?: string;
  datasource?: string | null;
}

export interface UpdateChatRequest {
  title: string;
}

export interface CreateMessageRequest {
  role: string;
  content: string;
  sql_query?: string | null;
  results_json?: string | null;
  tool_results?: Record<string, unknown>[] | null;
  reasoning_steps?: Record<string, unknown>[] | null;
  langfuse_trace_id?: string | null;
}

export interface CreateMessageFeedbackRequest {
  rating: MessageFeedbackRating;
  saved_time?: string | null;
  comment?: string | null;
}

/**
 * List all chats for current user.
 */
export async function listChats(): Promise<ChatResponse[]> {
  return request<ChatResponse[]>('/api/chats');
}

/**
 * Create a new chat.
 */
export async function createChat(data?: CreateChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chats', {
    method: 'POST',
    body: JSON.stringify(data || { title: 'Nowy czat' }),
  });
}

/**
 * Get a specific chat.
 */
export async function getChat(chatId: string): Promise<ChatResponse> {
  return request<ChatResponse>(`/api/chats/${chatId}`);
}

/**
 * Update a chat.
 */
export async function updateChat(chatId: string, data: UpdateChatRequest): Promise<ChatResponse> {
  return request<ChatResponse>(`/api/chats/${chatId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

/**
 * Delete a chat.
 */
export async function deleteChat(chatId: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(`/api/chats/${chatId}`, {
    method: 'DELETE',
  });
}

/**
 * List messages in a chat.
 */
export async function listMessages(chatId: string): Promise<ChatMessageResponse[]> {
  return request<ChatMessageResponse[]>(`/api/chats/${chatId}/messages`);
}

/**
 * Create a message in a chat.
 */
export async function createMessage(chatId: string, data: CreateMessageRequest): Promise<ChatMessageResponse> {
  return request<ChatMessageResponse>(`/api/chats/${chatId}/messages`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * Create or update feedback for an assistant message.
 */
export async function createMessageFeedback(
  chatId: string,
  messageId: string,
  data: CreateMessageFeedbackRequest
): Promise<ChatMessageFeedbackResponse> {
  return request<ChatMessageFeedbackResponse>(`/api/chats/${chatId}/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

/**
 * Delete the last N messages from a chat (used by retry).
 */
export async function deleteLastMessages(chatId: string, count = 2): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/chats/${chatId}/messages/latest?count=${count}`, {
    method: 'DELETE',
  });
}

/**
 * Search chats by title.
 */
export async function searchChats(query: string): Promise<ChatResponse[]> {
  return request<ChatResponse[]>(`/api/chats/search/${encodeURIComponent(query)}`);
}

// ============= Health API =============

export interface HealthResponse {
  status: string;
  components?: Record<string, string>;
}

/**
 * Check API health.
 */
export async function healthCheck(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

/**
 * Detailed health check.
 */
export async function detailedHealthCheck(): Promise<HealthResponse> {
  return request<HealthResponse>('/health/detailed');
}

// ============= Data Sources API =============

export interface WelcomeSuggestion {
  text: string;
  icon?: string;
}

export interface WelcomeInfo {
  title?: string;
  description?: string;
  suggestions: WelcomeSuggestion[];
}

export interface AgentInfo {
  icon?: string;
  color?: string;
}

export interface DataSourceInfo {
  name: string;
  display_name: string;
  description: string;
  agent?: AgentInfo;
  welcome?: WelcomeInfo;
}

export interface DataSourceListResponse {
  datasources: DataSourceInfo[];
}

export interface SuggestionsResponse {
  suggestions: string[];
}

/**
 * List available data sources.
 */
export async function listDataSources(): Promise<DataSourceListResponse> {
  return request<DataSourceListResponse>('/api/datasources');
}

/**
 * Get suggestions for a data source (or first available).
 */
export async function getSuggestions(datasource?: string): Promise<SuggestionsResponse> {
  if (datasource) {
    return request<SuggestionsResponse>(`/api/datasources/${datasource}/suggestions`);
  }
  // Get first available datasource
  const { datasources } = await listDataSources();
  if (datasources.length === 0) {
    return { suggestions: [] };
  }
  return request<SuggestionsResponse>(`/api/datasources/${datasources[0].name}/suggestions`);
}


// =============================================================================
// View Plugins
// =============================================================================

export interface ViewNavInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  label: string;
  order: number;
}

export interface ViewListResponse {
  views: ViewNavInfo[];
}

/**
 * List registered view plugins (for navigation rail).
 */
export async function listViews(): Promise<ViewListResponse> {
  return request<ViewListResponse>('/api/views');
}
