import { describe, it, expect } from "vitest";
import { resolveChatRouteAction } from "./chatRouteSync";

const KNOWN = new Set(["chat-a", "chat-b"]);
const EMPTY = new Set<string>();

describe("resolveChatRouteAction", () => {
  it("returns noop while chats are still loading", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: "chat-a",
        currentChatId: null,
        chatsLoaded: false,
        knownChatIds: EMPTY,
      })
    ).toEqual({ kind: "noop" });
  });

  it("loads URL chat when it exists and differs from currentChatId", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: "chat-a",
        currentChatId: null,
        chatsLoaded: true,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "load", chatId: "chat-a" });
  });

  it("loads URL chat when switching to a different existing chat", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: "chat-b",
        currentChatId: "chat-a",
        chatsLoaded: true,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "load", chatId: "chat-b" });
  });

  it("returns noop when URL chat matches currentChatId (avoids re-load loop)", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: "chat-a",
        currentChatId: "chat-a",
        chatsLoaded: true,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "noop" });
  });

  it("redirects home when URL chat is unknown (deleted / not owned by user)", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: "missing",
        currentChatId: null,
        chatsLoaded: true,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "redirect-home" });
  });

  it("redirects home when URL chat is unknown even if a different chat is open", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: "missing",
        currentChatId: "chat-a",
        chatsLoaded: true,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "redirect-home" });
  });

  it("starts new chat when URL has no id and a chat is currently open", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: undefined,
        currentChatId: "chat-a",
        chatsLoaded: true,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "start-new" });
  });

  it("returns noop when URL has no id and no chat is open", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: undefined,
        currentChatId: null,
        chatsLoaded: true,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "noop" });
  });

  it("returns noop while loading even if URL would otherwise trigger start-new", () => {
    expect(
      resolveChatRouteAction({
        urlChatId: undefined,
        currentChatId: "chat-a",
        chatsLoaded: false,
        knownChatIds: KNOWN,
      })
    ).toEqual({ kind: "noop" });
  });
});
