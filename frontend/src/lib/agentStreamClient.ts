import { authFetch } from "@/lib/api";
import i18n from "@/i18n";

export type SSEEventType =
  | "status"
  | "tool"
  | "token"
  | "token_reset"
  | "complete"
  | "error";

/**
 * Error thrown by streamAgent when the HTTP request fails.
 * Carries the status code so callers can react to specific errors (e.g. 403).
 */
export class StreamHttpError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "StreamHttpError";
  }
}

export interface StatusEvent {
  message: string;
  step: number;
  tool_id?: string;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  reasoning?: string | null;
  iteration?: number;
}

export interface ToolEvent {
  name: string;
  duration_ms: number;
  tool_id?: string;
  success?: boolean;
  row_count?: number | null;
  error?: string | null;
  result?: Record<string, unknown>;
}

export interface TokenEvent {
  delta: string;
}


export interface CompleteEvent {
  content: string | null;
  tool_history: Array<{
    tool: string;
    tool_call_id?: string;
    arguments: Record<string, unknown>;
    result: Record<string, unknown>;
    duration_ms: number;
  }>;
  iterations: number;
  source_type: string | null;
  error: string | null;
  langfuse_trace_id?: string | null;
}

export interface ErrorEvent {
  message: string;
  langfuse_trace_id?: string | null;
}

export interface AgentStreamHistoryEntry {
  role: string;
  content: string;
  queryResults?: Record<string, unknown>[];
  toolResults?: Record<string, unknown>[];
}

export interface AgentStreamRequest {
  question: string;
  conversationHistory?: AgentStreamHistoryEntry[];
  model?: string;
  datasource?: string;
  chat_id?: string;
}

export interface StreamCallbacks {
  onStatus?: (event: StatusEvent) => void;
  onTool?: (event: ToolEvent) => void;
  onToken?: (event: TokenEvent) => void;
  onTokenReset?: () => void;
  onComplete?: (event: CompleteEvent) => void;
  onError?: (event: ErrorEvent) => void;
}

export async function streamAgent(
  request: AgentStreamRequest,
  callbacks: StreamCallbacks,
  signal?: AbortSignal
): Promise<CompleteEvent | null> {
  const response = await authFetch("/api/agent/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new StreamHttpError(
      errorData.detail || errorData.error || `HTTP ${response.status}`,
      response.status,
    );
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error(i18n.t("errors:noResponseBody"));
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: CompleteEvent | null = null;
  let streamError: string | null = null;
  let currentEventType: SSEEventType | null = null;

  const processLine = (line: string): void => {
    const trimmedLine = line.trim();
    if (!trimmedLine) {
      return;
    }

    if (trimmedLine.startsWith("event:")) {
      currentEventType = trimmedLine.slice(6).trim() as SSEEventType;
      return;
    }

    if (!trimmedLine.startsWith("data:")) {
      return;
    }

    const dataStr = trimmedLine.slice(5).trim();
    if (!dataStr) {
      return;
    }

    try {
      const data = JSON.parse(dataStr);
      switch (currentEventType) {
        case "status":
          callbacks.onStatus?.(data as StatusEvent);
          break;
        case "tool":
          callbacks.onTool?.(data as ToolEvent);
          break;
        case "token":
          callbacks.onToken?.(data as TokenEvent);
          break;
        case "token_reset":
          callbacks.onTokenReset?.();
          break;
        case "complete":
          finalResult = data as CompleteEvent;
          callbacks.onComplete?.(finalResult);
          break;
        case "error":
          streamError = (data as ErrorEvent).message || i18n.t("errors:processing");
          callbacks.onError?.({ message: streamError });
          break;
      }
    } catch {
      console.warn("Failed to parse SSE data:", dataStr);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      processLine(line);
    }
  }

  // Flush any final bytes and parse trailing buffered line (even without newline terminator).
  buffer += decoder.decode();
  if (buffer.trim()) {
    processLine(buffer);
  }

  if (streamError) {
    return {
      content: null,
      tool_history: [],
      iterations: 0,
      source_type: null,
      error: streamError,
      langfuse_trace_id: null,
    };
  }

  return finalResult;
}
