import { afterEach, describe, expect, it, vi } from "vitest";
import {
  streamAgent,
  StreamHttpError,
  type CompleteEvent,
} from "./agentStreamClient";

// authFetch is a thin wrapper over global fetch in production. For these
// tests we replace it with a pass-through so the existing `fetch` stubs
// keep working without pulling in the real auth-session module.
vi.mock("@/lib/api", () => ({
  authFetch: (input: string, init?: RequestInit) => fetch(input, init),
}));

function createStreamBody(chunks: string[]) {
  const encoded = chunks.map((chunk) => new TextEncoder().encode(chunk));
  let index = 0;
  return {
    getReader() {
      return {
        async read(): Promise<{ done: boolean; value?: Uint8Array }> {
          if (index >= encoded.length) {
            return { done: true };
          }
          const value = encoded[index];
          index += 1;
          return { done: false, value };
        },
      };
    },
  };
}

function createOkResponse(chunks: string[]) {
  return {
    ok: true,
    body: createStreamBody(chunks),
    status: 200,
    async json() {
      return {};
    },
  };
}

describe("streamAgent", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses complete event from trailing buffer without newline", async () => {
    const completePayload: CompleteEvent = {
      content: "done",
      tool_history: [],
      iterations: 1,
      source_type: "plugin",
      error: null,
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        createOkResponse([
          "event: status\ndata: {\"message\":\"Analizuję\",\"step\":0}\n\n",
          `event: complete\ndata: ${JSON.stringify(completePayload)}`,
        ])
      )
    );

    const onComplete = vi.fn();
    const result = await streamAgent(
      { question: "test" },
      {
        onComplete,
      }
    );

    expect(result).toEqual(completePayload);
    expect(onComplete).toHaveBeenCalledWith(completePayload);
  });

  it("returns langfuse_trace_id from the complete event payload", async () => {
    const completePayload: CompleteEvent = {
      content: "done",
      tool_history: [],
      iterations: 1,
      source_type: "plugin",
      error: null,
      langfuse_trace_id: "0123456789abcdef0123456789abcdef",
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        createOkResponse([
          `event: complete\ndata: ${JSON.stringify(completePayload)}\n\n`,
        ])
      )
    );

    const onComplete = vi.fn();
    const result = await streamAgent(
      { question: "test" },
      {
        onComplete,
      }
    );

    expect(result.langfuse_trace_id).toBe("0123456789abcdef0123456789abcdef");
    expect(onComplete).toHaveBeenCalledWith(completePayload);
  });

  it("parses normal multi-event stream and returns final complete payload", async () => {
    const completePayload: CompleteEvent = {
      content: "final answer",
      tool_history: [],
      iterations: 2,
      source_type: "plugin",
      error: null,
    };

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        createOkResponse([
          "event: status\ndata: {\"message\":\"Analizuję\",\"step\":0}\n\n",
          "event: tool\ndata: {\"name\":\"generate_custom_sql\",\"duration_ms\":123}\n\n",
          `event: complete\ndata: ${JSON.stringify(completePayload)}\n\n`,
        ])
      )
    );

    const onStatus = vi.fn();
    const onTool = vi.fn();
    const result = await streamAgent(
      { question: "test" },
      {
        onStatus,
        onTool,
      }
    );

    expect(onStatus).toHaveBeenCalledWith({ message: "Analizuję", step: 0 });
    expect(onTool).toHaveBeenCalledWith({
      name: "generate_custom_sql",
      duration_ms: 123,
    });
    expect(result).toEqual(completePayload);
  });

  it("returns synthetic complete payload with error when error event is received", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        createOkResponse([
          "event: status\ndata: {\"message\":\"Analizuję\",\"step\":0}\n\n",
          "event: error\ndata: {\"message\":\"Agent failed\"}\n\n",
        ])
      )
    );

    const onError = vi.fn();
    const result = await streamAgent(
      { question: "test" },
      {
        onError,
      }
    );

    expect(onError).toHaveBeenCalledWith({ message: "Agent failed" });
    expect(result).toEqual({
      content: null,
      tool_history: [],
      iterations: 0,
      source_type: null,
      error: "Agent failed",
      langfuse_trace_id: null,
    });
  });

  it("throws StreamHttpError with status and detail on 403", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        async json() {
          return { detail: "Twój dostęp do chatbota wygasł." };
        },
      })
    );

    await expect(
      streamAgent({ question: "test" }, {})
    ).rejects.toThrow(StreamHttpError);

    try {
      await streamAgent({ question: "test" }, {});
    } catch (err) {
      expect(err).toBeInstanceOf(StreamHttpError);
      expect((err as StreamHttpError).status).toBe(403);
      expect((err as StreamHttpError).message).toBe(
        "Twój dostęp do chatbota wygasł."
      );
    }
  });

  it("throws StreamHttpError with status on 429 rate limit", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 429,
        async json() {
          return { detail: "Rate limit exceeded" };
        },
      })
    );

    try {
      await streamAgent({ question: "test" }, {});
    } catch (err) {
      expect(err).toBeInstanceOf(StreamHttpError);
      expect((err as StreamHttpError).status).toBe(429);
      expect((err as StreamHttpError).message).toBe("Rate limit exceeded");
    }
  });

  it("falls back to HTTP status when json parsing fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        async json() {
          throw new Error("not json");
        },
      })
    );

    try {
      await streamAgent({ question: "test" }, {});
    } catch (err) {
      expect(err).toBeInstanceOf(StreamHttpError);
      expect((err as StreamHttpError).status).toBe(500);
      expect((err as StreamHttpError).message).toBe("HTTP 500");
    }
  });
});

describe("streamAgent abort", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function createAbortableResponse(
    chunks: string[],
    signal: AbortSignal,
  ) {
    const encoded = chunks.map((chunk) => new TextEncoder().encode(chunk));
    let index = 0;
    return {
      ok: true,
      status: 200,
      async json() {
        return {};
      },
      body: {
        getReader() {
          return {
            async read(): Promise<{ done: boolean; value?: Uint8Array }> {
              if (signal.aborted) {
                const err = new Error("aborted");
                err.name = "AbortError";
                throw err;
              }
              if (index >= encoded.length) {
                return { done: true };
              }
              const value = encoded[index];
              index += 1;
              return { done: false, value };
            },
          };
        },
      },
    };
  }

  it("rejects with AbortError when the signal is aborted mid-stream", async () => {
    const controller = new AbortController();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((_url: string, init: RequestInit) => {
        return Promise.resolve(
          createAbortableResponse(
            [
              "event: token\ndata: {\"delta\":\"Hel\"}\n\n",
              "event: token\ndata: {\"delta\":\"lo\"}\n\n",
            ],
            init.signal as AbortSignal,
          ),
        );
      }),
    );

    const tokens: string[] = [];
    const promise = streamAgent(
      { question: "test" },
      {
        onToken: (event) => {
          tokens.push(event.delta);
          if (tokens.length === 1) {
            controller.abort();
          }
        },
      },
      controller.signal,
    );

    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    expect(tokens).toEqual(["Hel"]);
  });

  it("forwards the AbortSignal to fetch", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(
      createOkResponse([
        `event: complete\ndata: ${JSON.stringify({
          content: "ok",
          tool_history: [],
          iterations: 1,
          source_type: "plugin",
          error: null,
        })}\n\n`,
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    await streamAgent({ question: "test" }, {}, controller.signal);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
  });
});

describe("StreamHttpError", () => {
  it("carries status and message", () => {
    const err = new StreamHttpError("forbidden", 403);
    expect(err.message).toBe("forbidden");
    expect(err.status).toBe(403);
    expect(err.name).toBe("StreamHttpError");
    expect(err).toBeInstanceOf(Error);
  });
});
