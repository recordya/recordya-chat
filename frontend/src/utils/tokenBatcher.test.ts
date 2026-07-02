import { describe, it, expect, vi } from "vitest";
import { createTokenBatcher, type FlushScheduler } from "./tokenBatcher";

/**
 * Manual scheduler: captures the pending callback so tests can drive flushes
 * deterministically, mirroring a single requestAnimationFrame tick.
 */
function createManualScheduler() {
  let pending: (() => void) | null = null;
  let nextHandle = 1;
  const scheduler: FlushScheduler = {
    schedule: (callback) => {
      pending = callback;
      return nextHandle++;
    },
    cancel: () => {
      pending = null;
    },
  };
  return {
    scheduler,
    tick: () => {
      const callback = pending;
      pending = null;
      callback?.();
    },
    hasPending: () => pending !== null,
  };
}

describe("createTokenBatcher", () => {
  it("coalesces multiple deltas within one frame into a single flush", () => {
    const { scheduler, tick } = createManualScheduler();
    const onFlush = vi.fn();
    const batcher = createTokenBatcher(onFlush, scheduler);

    batcher.append("Hello ");
    batcher.append("stream");
    batcher.append("ing");

    expect(onFlush).not.toHaveBeenCalled();
    tick();

    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(onFlush).toHaveBeenCalledWith("Hello streaming");
  });

  it("schedules a new flush only after the previous frame fired", () => {
    const { scheduler, tick } = createManualScheduler();
    const onFlush = vi.fn();
    const batcher = createTokenBatcher(onFlush, scheduler);

    batcher.append("a");
    tick();
    batcher.append("b");
    tick();

    expect(onFlush).toHaveBeenCalledTimes(2);
    expect(onFlush).toHaveBeenLastCalledWith("ab");
  });

  it("keeps the full value synchronously even before a flush", () => {
    const { scheduler } = createManualScheduler();
    const batcher = createTokenBatcher(vi.fn(), scheduler);

    batcher.append("partial ");
    batcher.append("text");

    expect(batcher.value).toBe("partial text");
  });

  it("flushNow cancels the pending frame and emits immediately", () => {
    const { scheduler, hasPending } = createManualScheduler();
    const onFlush = vi.fn();
    const batcher = createTokenBatcher(onFlush, scheduler);

    batcher.append("done");
    batcher.flushNow();

    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(onFlush).toHaveBeenCalledWith("done");
    expect(hasPending()).toBe(false);
  });

  it("reset clears the buffer, cancels pending flush, and emits empty", () => {
    const { scheduler, hasPending } = createManualScheduler();
    const onFlush = vi.fn();
    const batcher = createTokenBatcher(onFlush, scheduler);

    batcher.append("stale tokens");
    batcher.reset();

    expect(onFlush).toHaveBeenCalledWith("");
    expect(batcher.value).toBe("");
    expect(hasPending()).toBe(false);
  });
});
