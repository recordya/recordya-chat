import { describe, it, expect } from "vitest";
import { shouldUpdateMessages, shouldShowProcessing, computeRetryAction } from "./chatIsolation";

describe("shouldUpdateMessages", () => {
  it("returns true when user is still viewing the request's chat", () => {
    expect(shouldUpdateMessages("chat-1", "chat-1")).toBe(true);
  });

  it("returns false when user switched to a different chat", () => {
    expect(shouldUpdateMessages("chat-2", "chat-1")).toBe(false);
  });

  it("returns false when currentChatId is null (new empty chat view)", () => {
    expect(shouldUpdateMessages(null, "chat-1")).toBe(false);
  });
});

describe("shouldShowProcessing", () => {
  it("returns true when processing and viewing the same chat", () => {
    expect(shouldShowProcessing(true, "chat-1", "chat-1")).toBe(true);
  });

  it("returns false when processing but user switched to another chat", () => {
    expect(shouldShowProcessing(true, "chat-1", "chat-2")).toBe(false);
  });

  it("returns false when processing but user is on a new empty chat (null)", () => {
    expect(shouldShowProcessing(true, "chat-1", null)).toBe(false);
  });

  it("returns false when not processing even if chat IDs match", () => {
    expect(shouldShowProcessing(false, "chat-1", "chat-1")).toBe(false);
  });

  it("returns false when not processing and processingChatId is null (idle)", () => {
    expect(shouldShowProcessing(false, null, "chat-1")).toBe(false);
  });

  it("returns false when processing but processingChatId is null (edge case)", () => {
    expect(shouldShowProcessing(true, null, "chat-1")).toBe(false);
  });

  it("returns false when everything is null / idle", () => {
    expect(shouldShowProcessing(false, null, null)).toBe(false);
  });
});


describe("computeRetryAction", () => {
  const msg = (id: string, role: string, content: string) => ({ id, role, content });

  it("returns removeIds for both the error and the preceding user message", () => {
    const messages = [
      msg("u1", "user", "Wskaż 3 głosy kobiece"),
      msg("e1", "assistant", "Something went wrong. Please try again."),
    ];
    const action = computeRetryAction(messages, "e1");
    expect(action).not.toBeNull();
    expect(action!.question).toBe("Wskaż 3 głosy kobiece");
    expect(action!.removeIds).toEqual(["e1", "u1"]);
  });

  it("skips intermediate assistant messages when finding the user message", () => {
    const messages = [
      msg("u1", "user", "First question"),
      msg("a1", "assistant", "First answer"),
      msg("u2", "user", "Second question"),
      msg("a2", "assistant", "Partial answer"),
      msg("e1", "assistant", "Something went wrong. Please try again."),
    ];
    const action = computeRetryAction(messages, "e1");
    expect(action).not.toBeNull();
    expect(action!.question).toBe("Second question");
    expect(action!.removeIds).toEqual(["e1", "u2"]);
  });

  it("returns null when error message is the first message", () => {
    const messages = [
      msg("e1", "assistant", "Something went wrong."),
    ];
    expect(computeRetryAction(messages, "e1")).toBeNull();
  });

  it("returns null when there is no preceding user message", () => {
    const messages = [
      msg("a1", "assistant", "Welcome"),
      msg("e1", "assistant", "Something went wrong."),
    ];
    expect(computeRetryAction(messages, "e1")).toBeNull();
  });

  it("returns null when errorMessageId is not found", () => {
    const messages = [
      msg("u1", "user", "Hello"),
      msg("a1", "assistant", "Hi there"),
    ];
    expect(computeRetryAction(messages, "nonexistent")).toBeNull();
  });
});
