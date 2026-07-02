# Streaming Protocol (SSE)

The agent endpoint `POST /api/agent/stream` returns a [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) stream produced by `AgentService.run()`. The same generator powers both `ManagedPlugin` (service-managed tool loop) and `ExecutablePlugin` (plugin-controlled `run()`). Each event has a `type` and a `data` payload; the response writer serialises them as standard SSE frames:

```
event: <type>
data: <json payload>

```

## 1. Event Types

| Event | When emitted | Purpose |
|-------|--------------|---------|
| `status` | Before each LLM call and before each tool execution | Drives the "what is happening now?" UI hint |
| `tool` | After a tool execution completes | Reports tool result, duration, error |
| `token` | Per text delta returned by the LLM (Variant B) | Live, token-by-token rendering of assistant text |
| `token_reset` | The leaked-tool guard discards streamed tokens before a retry | Tells the FE to drop the partial draft |
| `complete` | Exactly once, at the end of a successful run | Final assistant content + full tool history |
| `error` | On a non-recoverable failure | Surfaces a user-friendly error message |

### `status` — `{"message": str, "step": int, "tool_id"?, "tool_name"?, "arguments"?, "reasoning"?}`

Two flavours: a generic "Analyzing…" hint at the start of each iteration, and a tool-specific hint emitted right before `execute_tool()` runs. The tool-specific variant carries the parsed tool id, tool name, arguments, and the optional `reasoning` field the model produced.

### `tool` — `{"name", "duration_ms", "tool_id", "success", "row_count", "error", "result"}`

Emitted exactly once per tool call after execution. `result` is the full plugin response dict (`success`, `result`, `row_count`, `error`, plus any plugin-specific extras).

### `token` — `{"delta": str}`

A non-empty fragment of assistant text from the LLM stream. Tokens may arrive in any granularity (single characters or longer chunks) and must be concatenated by the consumer.

### `token_reset` — `{}`

Empty payload. Means: "discard everything you have accumulated from `token` events for the current assistant message." Emitted only when the leaked-tool guard detects that the model streamed a fake/leaked tool call as plain text and the service is about to retry the same iteration.

### `complete` — `AgentResponse`

```json
{
  "content": "Final assistant text or null",
  "tool_history": [
    {"tool": "...", "arguments": {...}, "result": {...}, "duration_ms": 123}
  ],
  "iterations": 2,
  "source_type": "sql",
  "error": null,
  "langfuse_trace_id": "lf-trace-id-or-null"
}
```

`error` is `null` for a normal completion. It carries a machine-readable code (e.g. `"max_iterations_reached"`) when the loop terminated abnormally but still produced a user-facing message in `content`. `langfuse_trace_id` is the 32-char Langfuse trace id (or `null` when Langfuse is disabled); the frontend persists it on the assistant message so user feedback can be linked back to the trace as a `user_feedback` score.

### `error` — `{"message": str, "langfuse_trace_id"?: str}`

Emitted instead of `complete` for fatal failures. `message` is a user-friendly localized string mapped from the raw exception by `_friendly_error_message()`.

## 2. Token Streaming (Variant B)

Goal: render assistant text live, never leak tool-call JSON or widget JSON into the chat bubble.

Rules enforced in `AgentService._stream_llm()`:

1. **Text deltas stream as `token` events** while no tool call has started in the current iteration.
2. **As soon as the provider emits `tool_call_started`** (or the aggregated `final` chunk reports `tool_calls`), the iteration flips `seen_tool_calls = True` and **all subsequent content deltas in that iteration are dropped** from the SSE stream. The same JSON payload still reaches the plugin via `tool_calls` on the final chunk — only the *text channel* is silenced.
3. **The next iteration starts with `seen_tool_calls = False`**, so the model's commentary on the tool result streams normally again. This is what gives the UI live text *over* a widget without flicker.

In practice:

| Iteration | What the provider yields | What the SSE stream contains |
|-----------|--------------------------|------------------------------|
| 1 (decides to call a tool) | `tool_call_started` + `tool_calls` JSON deltas + `final` | `status` (analyzing), `status` (tool hint), `tool` |
| 2 (comments on result) | content deltas + `final` | `status` (analyzing), `token`, `token`, …, `complete` |

## 3. `token_reset` and the Leaked-Tool Guard

LLMs occasionally answer with text that *looks* like a tool call, e.g. `functions.search({"q":"x"})`, or paste a widget JSON object as plain text. `LeakedToolGuard` detects these patterns and forces a single retry with a correction prompt.

If the leaked draft was already streamed token-by-token (Variant B optimistically forwards text), the service emits a `token_reset` event *before* retrying so the FE can wipe the partial bubble:

```
event: token         data: {"delta": "functions.search("}
event: token         data: {"delta": "{\"q\":\"x\"})"}
event: token_reset   data: {}
event: token         data: {"delta": "Found "}
event: token         data: {"delta": "3 results."}
event: complete      data: {...}
```

Frontend handling: `useAgentStream.onTokenReset()` calls the token batcher's `reset()` (cancels any pending frame flush and clears its buffer), so the retry tokens land in a clean buffer.

## 4. Role-Based Redaction

`chat.py::_redact_event` filters event payloads per consumer role before serialisation:

- **Super admin** — full payloads (tool ids, arguments, results, errors).
- **Everyone else (incl. `admin`)** — `status` keeps only `message` / `step`, `tool` keeps only `name` / `duration_ms`. `token`, `token_reset`, `complete`, and `error` are pure UX signals and always pass through unchanged.

The same role gate is applied at write time in `chats.py` (only `super_admin` clients can persist `reasoning_steps`) and at read time in `GET /api/chats/{id}/messages` (returns `null` for everyone except `super_admin`).

## 5. Provider Contract — `BaseLLMProvider.stream()`

`AgentService` consumes the provider stream via `_iter_llm_chunks()`. A provider that natively supports streaming yields dicts in one of three shapes:

| Chunk | Meaning |
|-------|---------|
| `{"type": "content", "delta": str}` | Partial assistant text. May arrive any number of times. |
| `{"type": "tool_call_started"}` | Sentinel — the model committed to a tool call; further tool-call deltas will follow. Used by `_stream_llm` to suppress text on the SSE channel from that point in the iteration. |
| `{"type": "final", **complete_result}` | Emitted exactly once at the end. Same shape as `complete()`'s return value: `content`, `tool_calls`, `usage`, `model`, optional `request_overrides`. |

The `tool_call_started` chunk is optional. Providers that don't emit it (including the `BaseLLMProvider.stream()` default implementation, which just wraps `complete()` and yields a single `final`) are still safe: `_stream_llm` also flips `seen_tool_calls` when `final.tool_calls` is non-empty, so a single-chunk provider with tool calls produces zero `token` events.

`OpenAIProvider.stream()` is the reference implementation:

- Each upstream chunk's `choices[0].delta.content` becomes a `content` chunk.
- The first delta for a given tool-call index yields `tool_call_started` exactly once for that index.
- Tool-call deltas (`id`, `name`, `arguments`) are accumulated internally and surfaced only via the final `tool_calls` array — never on the text channel.
- The provider requests `stream_options={"include_usage": True}` so the final chunk carries token usage.

## 6. Frontend Consumption

`core/frontend/src/lib/agentStreamClient.ts` exposes `streamAgent()` with typed callbacks for each event type and an optional `AbortSignal`. `core/frontend/src/hooks/useAgentStream.ts` wires those callbacks to local state:

- `onToken` forwards `delta` to a token batcher (`core/frontend/src/utils/tokenBatcher.ts`) via `append()`. The batcher accumulates deltas in a synchronous buffer and coalesces state updates to at most once per animation frame (`requestAnimationFrame`), so a burst of `token` events triggers a single re-render / markdown re-parse instead of one per token.
- `onTokenReset` calls the batcher's `reset()`, cancelling any pending frame flush and clearing the buffer.
- `onComplete` calls the batcher's `flushNow()` (cancels the pending frame flush and emits the full buffer immediately so the final frame is never truncated), then replaces the streamed text with the canonical `content` from the `complete` event and exposes the full `tool_history` to downstream renderers (`ResultRegistry`, widgets, reasoning panel).
- `abort()` aborts the underlying `fetch` via `AbortController` and calls the batcher's `flushNow()`. The in-flight `runQuery` promise resolves with `{ aborted: true, partialContent }`, where `partialContent` is read from the batcher's synchronously-accurate `value` (everything streamed so far, independent of frame cadence). The chat composer's send button turns into a stop button while `isStreaming` is `true` and triggers `abort()`.

Streamed text and the final widget are independent: widgets render from `tool_history` in the `complete` event, not from the `token` stream.

## 7. Cancellation (Stop Button)

When the user clicks stop, the frontend calls `AbortController.abort()` on the `fetch`. The cancellation chain is fully standard `asyncio`:

1. The browser closes the TCP connection.
2. `sse-starlette`'s `EventSourceResponse` detects the disconnect and cancels the task driving the SSE generator.
3. `CancelledError` propagates through every `await` in `AgentService.run()` → `_stream_llm()` → `_iter_llm_chunks()` → `BaseLLMProvider.stream()`.
4. Provider implementations must let `CancelledError` propagate so the underlying HTTP stream to the upstream LLM is closed. `OpenAIProvider.stream()` satisfies this by iterating the SDK's `AsyncStream` with a plain `async for`; do not catch `BaseException` / `CancelledError` in a provider's `stream()` implementation.

No `complete` or `error` SSE event is emitted on cancellation. Tokens delivered before the abort remain in the hook's `partialContent`; the frontend persists them as the assistant message so the conversation history reflects what the user saw on screen (ChatGPT-style).

## 8. Testing

Streaming behaviour is covered by:

- `core/backend/tests/test_openai_provider_stream.py` — `OpenAIProvider.stream()` contract: content deltas, `tool_call_started` emission rules, parallel tool calls, usage propagation, request overrides.
- `core/backend/tests/test_agent_service.py` (Streaming section) — `AgentService._stream_llm()` and `run()`: token forwarding, Variant B suppression after `tool_call_started`, suppression when only a `final` chunk reports `tool_calls`, empty-delta filtering, `token_reset` emission on leaked-tool retry, task-cancellation propagation into the provider stream and preservation of partial tokens.
- `core/frontend/src/lib/agentStreamClient.test.ts` — SSE wire parsing on the consumer side, plus `AbortSignal` forwarding and mid-stream abort behaviour.
- `core/frontend/src/utils/tokenBatcher.test.ts` — token batcher unit tests: synchronous `value` accuracy, one flush per scheduled frame (coalescing a burst into a single update), `flushNow()` on completion/abort, and `reset()` cancelling a pending flush.

When adding a new provider, mirror the assertions in `test_openai_provider_stream.py` against the provider's chunk-yielding code path, and add a cancellation test analogous to `test_streaming_task_cancellation_propagates_to_llm_stream`.

