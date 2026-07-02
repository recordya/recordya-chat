/**
 * Hook for streaming agent responses via SSE (Server-Sent Events).
 * Provides real-time status updates during query processing.
 */

import { useState, useCallback, useRef } from "react";
import {
  AgentStreamRequest,
  CompleteEvent,
  ErrorEvent,
  StatusEvent,
  StreamHttpError,
  TokenEvent,
  ToolEvent,
  streamAgent,
} from "@/lib/agentStreamClient";
import { createTokenBatcher, type TokenBatcher } from "@/utils/tokenBatcher";
import i18n from "@/i18n";

export interface ReasoningStep {
  toolId: string;
  toolName: string;
  reasoning: string | null;
  message: string;
  arguments: Record<string, unknown>;
  iteration: number;
  status: "running" | "done" | "error";
  durationMs?: number;
  rowCount?: number | null;
  error?: string | null;
  result?: Record<string, unknown>;
}

export interface StreamQueryResult {
  result: CompleteEvent | null;
  error: string | null;
  httpStatus: number | null;
  steps: ReasoningStep[];
  aborted: boolean;
  partialContent: string;
}

// Hook return type
export interface UseAgentStreamResult {
  status: string;
  steps: ReasoningStep[];
  isStreaming: boolean;
  streamedContent: string;
  result: CompleteEvent | null;
  error: string | null;
  runQuery: (request: AgentStreamRequest) => Promise<StreamQueryResult>;
  abort: () => void;
  reset: () => void;
}

/**
 * Hook for streaming agent responses with real-time status updates.
 *
 * Usage:
 * ```tsx
 * const { status, isStreaming, result, error, runQuery } = useAgentStream();
 *
 * const handleSubmit = async (question: string) => {
 *   const result = await runQuery({ question });
 *   if (result) {
 *     console.log("Final answer:", result.content);
 *   }
 * };
 * ```
 */
export function useAgentStream(): UseAgentStreamResult {
  const [status, setStatus] = useState<string>(i18n.t("chat:statusReady"));
  const [steps, setSteps] = useState<ReasoningStep[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamedContent, setStreamedContent] = useState<string>("");
  const [result, setResult] = useState<CompleteEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const stepsRef = useRef<ReasoningStep[]>([]);

  // Coalesces token deltas into one flush per animation frame for smooth
  // streaming. Created lazily so the closure over setStreamedContent is stable.
  const batcherRef = useRef<TokenBatcher | null>(null);
  if (batcherRef.current === null) {
    batcherRef.current = createTokenBatcher((text) => setStreamedContent(text));
  }

  // Clears all stream state so a stale reasoning panel / answer from the
  // previous turn cannot flash before the next stream starts emitting.
  const reset = useCallback(() => {
    stepsRef.current = [];
    setSteps([]);
    setResult(null);
    setError(null);
    batcherRef.current?.reset();
    setStatus(i18n.t("chat:statusAnalyzing"));
  }, []);

  const abort = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      batcherRef.current?.flushNow();
      setIsStreaming(false);
      setStatus(i18n.t("chat:statusCancelled"));
    }
  }, []);

  const runQuery = useCallback(
    async (request: AgentStreamRequest): Promise<StreamQueryResult> => {
      setIsStreaming(true);
      reset();

      abortControllerRef.current = new AbortController();

      try {
        const finalResult = await streamAgent(
          request,
          {
            onStatus: (data: StatusEvent) => {
              setStatus(data.message);
              if (data.tool_id && data.tool_name) {
                const step: ReasoningStep = {
                  toolId: data.tool_id,
                  toolName: data.tool_name,
                  reasoning: data.reasoning ?? null,
                  message: data.message,
                  arguments: data.arguments ?? {},
                  iteration: data.iteration ?? data.step,
                  status: "running",
                };
                stepsRef.current = [...stepsRef.current, step];
                setSteps(stepsRef.current);
              }
            },
            onTool: (data: ToolEvent) => {
              if (!data.tool_id) {
                return;
              }
              stepsRef.current = stepsRef.current.map((step) =>
                step.toolId === data.tool_id
                  ? {
                      ...step,
                      status: data.error ? "error" : "done",
                      durationMs: data.duration_ms,
                      rowCount: data.row_count ?? null,
                      error: data.error ?? null,
                      result: data.result,
                    }
                  : step
              );
              setSteps(stepsRef.current);
            },
            onToken: (data: TokenEvent) => {
              batcherRef.current?.append(data.delta);
            },
            onTokenReset: () => {
              batcherRef.current?.reset();
            },
            onComplete: (data: CompleteEvent) => {
              batcherRef.current?.flushNow();
              setResult(data);
              setStatus(i18n.t("chat:statusReady"));
            },
            onError: (data: ErrorEvent) => {
              setError(data.message);
              setStatus(i18n.t("chat:statusError"));
            },
          },
          abortControllerRef.current.signal
        );

        setIsStreaming(false);
        return {
          result: finalResult,
          error: null,
          httpStatus: null,
          steps: stepsRef.current,
          aborted: false,
          partialContent: batcherRef.current?.value ?? "",
        };
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          setStatus(i18n.t("chat:statusCancelled"));
          return {
            result: null,
            error: null,
            httpStatus: null,
            steps: stepsRef.current,
            aborted: true,
            partialContent: batcherRef.current?.value ?? "",
          };
        }
        const errorMessage =
          err instanceof Error ? err.message : i18n.t("errors:unexpected");
        const httpStatus =
          err instanceof StreamHttpError ? err.status : null;
        setError(errorMessage);
        setStatus(i18n.t("chat:statusError"));
        setIsStreaming(false);
        return {
          result: null,
          error: errorMessage,
          httpStatus,
          steps: stepsRef.current,
          aborted: false,
          partialContent: batcherRef.current?.value ?? "",
        };
      } finally {
        abortControllerRef.current = null;
      }
    },
    [reset]
  );

  return {
    status,
    steps,
    isStreaming,
    streamedContent,
    result,
    error,
    runQuery,
    abort,
    reset,
  };
}
