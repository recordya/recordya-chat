import { describe, it, expect } from "vitest";
import {
  distanceFromBottom,
  isScrolledToBottom,
  SCROLL_BOTTOM_THRESHOLD_PX,
} from "./scroll";

describe("distanceFromBottom", () => {
  it("is 0 when fully scrolled to the bottom", () => {
    expect(
      distanceFromBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 }),
    ).toBe(0);
  });

  it("returns the hidden pixel count when scrolled up", () => {
    expect(
      distanceFromBottom({ scrollTop: 0, scrollHeight: 1000, clientHeight: 100 }),
    ).toBe(900);
  });

  it("grows as content streams in below the viewport", () => {
    const before = distanceFromBottom({ scrollTop: 400, scrollHeight: 1000, clientHeight: 100 });
    const after = distanceFromBottom({ scrollTop: 400, scrollHeight: 1400, clientHeight: 100 });
    expect(after).toBeGreaterThan(before);
  });
});

describe("isScrolledToBottom", () => {
  it("is true at the exact bottom", () => {
    expect(
      isScrolledToBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 }),
    ).toBe(true);
  });

  it("is true within the default threshold", () => {
    expect(
      isScrolledToBottom({
        scrollTop: 900 - SCROLL_BOTTOM_THRESHOLD_PX,
        scrollHeight: 1000,
        clientHeight: 100,
      }),
    ).toBe(true);
  });

  it("is false just beyond the default threshold", () => {
    expect(
      isScrolledToBottom({
        scrollTop: 900 - (SCROLL_BOTTOM_THRESHOLD_PX + 1),
        scrollHeight: 1000,
        clientHeight: 100,
      }),
    ).toBe(false);
  });

  it("is false when streamed content pushes the user far from the bottom", () => {
    // User stays put while ~400px of new tokens stream in below the fold:
    // the button should be revealed (not near bottom).
    expect(
      isScrolledToBottom({ scrollTop: 500, scrollHeight: 1400, clientHeight: 100 }),
    ).toBe(false);
  });

  it("respects a custom threshold", () => {
    const metrics = { scrollTop: 700, scrollHeight: 1000, clientHeight: 100 };
    expect(isScrolledToBottom(metrics)).toBe(false);
    expect(isScrolledToBottom(metrics, 250)).toBe(true);
  });
});
