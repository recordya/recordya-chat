import { describe, it, expect } from "vitest";
import { getNextChatIndexAfterDelete } from "./useChatSelection";
import { apiMessageToMessage, messageToCreateRequest } from "./use-chat-history";
import type { Message } from "@/components/ChatMessage";
import type { ChatMessageResponse } from "@/lib/api";

describe("getNextChatIndexAfterDelete", () => {
  it("selects next chat below after deletion (or above if last)", () => {
    // Middle of list: index 1 deleted, 4 remaining → select index 1 (was below)
    expect(getNextChatIndexAfterDelete(1, 4)).toBe(1);
    // Last item: index 4 deleted, 4 remaining → select index 3 (new last)
    expect(getNextChatIndexAfterDelete(4, 4)).toBe(3);
    // First item: index 0 deleted, 4 remaining → select index 0 (new first)
    expect(getNextChatIndexAfterDelete(0, 4)).toBe(0);
    // Empty list: → null
    expect(getNextChatIndexAfterDelete(0, 0)).toBeNull();
  });
});

const baseApiMessage: ChatMessageResponse = {
  id: "m1",
  role: "assistant",
  content: "hello",
  sql_query: null,
  results_json: null,
  tool_results: null,
  reasoning_steps: null,
  langfuse_trace_id: null,
  feedback: null,
  created_at: "2026-01-01T00:00:00Z",
};

describe("apiMessageToMessage", () => {
  it("maps minimal API message with all optional fields null", () => {
    expect(apiMessageToMessage(baseApiMessage)).toEqual({
      id: "m1",
      role: "assistant",
      content: "hello",
      isPersisted: true,
      sql: undefined,
      sqlMode: undefined,
      queryResults: undefined,
      toolResults: undefined,
      reasoningSteps: undefined,
      langfuseTraceId: undefined,
      feedback: undefined,
    });
  });

  it("maps langfuse_trace_id into langfuseTraceId", () => {
    const m = apiMessageToMessage({ ...baseApiMessage, langfuse_trace_id: "trace-123" });
    expect(m.langfuseTraceId).toBe("trace-123");
  });

  it("maps persisted feedback from API message", () => {
    const feedback = {
      id: "f1",
      message_id: "m1",
      chat_id: "c1",
      rating: "positive" as const,
      saved_time: "up_to_30_min",
      comment: "Helpful",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };

    const message = apiMessageToMessage({ ...baseApiMessage, feedback });

    expect(message.feedback).toEqual(feedback);
  });

  it("parses results_json into queryResults array", () => {
    const rows = [{ a: 1 }, { a: 2 }];
    const m = apiMessageToMessage({ ...baseApiMessage, results_json: JSON.stringify(rows) });
    expect(m.queryResults).toEqual(rows);
  });

  it("passes through sql_query as sql", () => {
    const m = apiMessageToMessage({ ...baseApiMessage, sql_query: "SELECT 1" });
    expect(m.sql).toBe("SELECT 1");
  });

  it("forwards tool_results unchanged", () => {
    const toolResults = [
      {
        tool: "execute_sql_query",
        tool_call_id: "c1",
        arguments: { sql: "SELECT 1" },
        result: { rows: [{ x: 1 }] },
        duration_ms: 12,
      },
    ];
    const m = apiMessageToMessage({
      ...baseApiMessage,
      tool_results: toolResults as unknown as Record<string, unknown>[],
    });
    expect(m.toolResults).toEqual(toolResults);
  });

  it("normalizes empty string sql_query to undefined", () => {
    const m = apiMessageToMessage({ ...baseApiMessage, sql_query: "" });
    expect(m.sql).toBeUndefined();
  });
});

const baseMessage: Message = {
  id: "tmp-1",
  role: "assistant",
  content: "answer",
};

describe("messageToCreateRequest", () => {
  it("emits nulls for all optional fields when nothing is provided", () => {
    expect(messageToCreateRequest(baseMessage)).toEqual({
      role: "assistant",
      content: "answer",
      sql_query: null,
      results_json: null,
      tool_results: null,
      reasoning_steps: null,
      langfuse_trace_id: null,
    });
  });

  it("forwards langfuseTraceId into langfuse_trace_id payload", () => {
    const req = messageToCreateRequest({ ...baseMessage, langfuseTraceId: "trace-abc" });
    expect(req.langfuse_trace_id).toBe("trace-abc");
  });

  it("serializes results array into results_json string", () => {
    const rows = [{ a: 1 }];
    const req = messageToCreateRequest(baseMessage, "SELECT 1", rows);
    expect(req.sql_query).toBe("SELECT 1");
    expect(req.results_json).toBe(JSON.stringify(rows));
  });

  it("forwards tool_results from Message to API payload", () => {
    const toolResults = [
      {
        tool: "execute_sql_query",
        tool_call_id: "c1",
        arguments: {},
        result: { rows: [] },
      },
    ];
    const req = messageToCreateRequest({
      ...baseMessage,
      toolResults,
    });
    expect(req.tool_results).toEqual(toolResults);
  });

  it("treats empty string sqlQuery as null (does not persist empty SQL)", () => {
    const req = messageToCreateRequest(baseMessage, "", undefined);
    expect(req.sql_query).toBeNull();
  });

  it("round-trips a message through messageToCreateRequest and apiMessageToMessage", () => {
    const message: Message = {
      id: "orig",
      role: "assistant",
      content: "answer",
      sql: "SELECT 1",
      queryResults: [{ a: 1 }],
      toolResults: [
        { tool: "f", tool_call_id: "c1", arguments: {}, result: { ok: true } },
      ],
    };
    const req = messageToCreateRequest(message, message.sql, message.queryResults);
    const restored = apiMessageToMessage({
      id: "m-new",
      role: req.role,
      content: req.content,
      sql_query: req.sql_query ?? null,
      results_json: req.results_json ?? null,
      tool_results: req.tool_results ?? null,
      reasoning_steps: req.reasoning_steps ?? null,
      langfuse_trace_id: req.langfuse_trace_id ?? null,
      feedback: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    expect(restored.content).toBe(message.content);
    expect(restored.sql).toBe(message.sql);
    expect(restored.queryResults).toEqual(message.queryResults);
    expect(restored.toolResults).toEqual(message.toolResults);
  });
});
