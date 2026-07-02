/**
 * Coalesces streamed token deltas into at most one flush per animation frame.
 *
 * Token events can arrive far faster than the screen refreshes. Calling
 * setState (and re-parsing markdown) on every delta makes streaming visibly
 * choppy and grows quadratically with response length. This helper accumulates
 * deltas synchronously and flushes the full buffer at most once per scheduler
 * tick, keeping the live bubble smooth while preserving correctness.
 *
 * The scheduler is injectable so the coalescing logic can be unit-tested
 * deterministically without relying on a real `requestAnimationFrame`.
 */

export interface FlushScheduler {
  schedule: (callback: () => void) => number;
  cancel: (handle: number) => void;
}

export const rafScheduler: FlushScheduler = {
  schedule: (callback) => requestAnimationFrame(callback),
  cancel: (handle) => cancelAnimationFrame(handle),
};

export interface TokenBatcher {
  /** Append a token delta; schedules a flush if one is not already pending. */
  append: (delta: string) => void;
  /** Cancel any pending flush and emit the current buffer immediately. */
  flushNow: () => void;
  /** Cancel any pending flush and clear the buffer (emits an empty string). */
  reset: () => void;
  /** The full text accumulated so far (always synchronously up to date). */
  readonly value: string;
}

/**
 * Create a token batcher.
 *
 * @param onFlush  - Called with the full accumulated text when a flush occurs.
 * @param scheduler - Frame scheduler (defaults to `requestAnimationFrame`).
 */
export function createTokenBatcher(
  onFlush: (text: string) => void,
  scheduler: FlushScheduler = rafScheduler,
): TokenBatcher {
  let buffer = "";
  let scheduled: number | null = null;

  const cancelScheduled = (): void => {
    if (scheduled !== null) {
      scheduler.cancel(scheduled);
      scheduled = null;
    }
  };

  return {
    append(delta: string): void {
      buffer += delta;
      if (scheduled === null) {
        scheduled = scheduler.schedule(() => {
          scheduled = null;
          onFlush(buffer);
        });
      }
    },
    flushNow(): void {
      cancelScheduled();
      onFlush(buffer);
    },
    reset(): void {
      cancelScheduled();
      buffer = "";
      onFlush("");
    },
    get value(): string {
      return buffer;
    },
  };
}
