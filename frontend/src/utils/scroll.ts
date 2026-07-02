/** Pixel tolerance for treating the scroll position as "at the bottom". */
export const SCROLL_BOTTOM_THRESHOLD_PX = 100;

export interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

/** Pixels of content hidden below the current viewport. */
export function distanceFromBottom({
  scrollTop,
  scrollHeight,
  clientHeight,
}: ScrollMetrics): number {
  return scrollHeight - scrollTop - clientHeight;
}

/** Whether the viewport is at (or within the threshold of) the bottom. */
export function isScrolledToBottom(
  metrics: ScrollMetrics,
  threshold: number = SCROLL_BOTTOM_THRESHOLD_PX,
): boolean {
  return distanceFromBottom(metrics) <= threshold;
}
