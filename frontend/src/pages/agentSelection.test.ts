import { describe, it, expect } from "vitest";
import { resolveSelectedAgent, type AgentSelectionInput } from "./agentSelection";

const BASE: AgentSelectionInput = {
  agentsLoaded: true,
  chatsLoaded: true,
  urlChatId: undefined,
  currentChatId: null,
  selectedAgent: null,
  availableAgents: ["agent-a", "agent-b"],
  currentChatDatasource: null,
};

describe("resolveSelectedAgent", () => {
  it("waits while agents or chats are still loading", () => {
    expect(resolveSelectedAgent({ ...BASE, agentsLoaded: false })).toEqual({ kind: "noop" });
    expect(resolveSelectedAgent({ ...BASE, chatsLoaded: false })).toEqual({ kind: "noop" });
  });

  it("waits for a deep-linked chat to load before deciding", () => {
    expect(
      resolveSelectedAgent({
        ...BASE,
        urlChatId: "chat-a",
        currentChatId: null,
        selectedAgent: "agent-a",
      })
    ).toEqual({ kind: "noop" });
  });

  it("adopts the open chat's datasource when the URL points to it", () => {
    expect(
      resolveSelectedAgent({
        ...BASE,
        urlChatId: "chat-a",
        currentChatId: "chat-a",
        selectedAgent: "agent-a",
        currentChatDatasource: "agent-b",
      })
    ).toEqual({ kind: "select", agent: "agent-b" });
  });

  it("is a noop when selection already matches the open chat's datasource", () => {
    expect(
      resolveSelectedAgent({
        ...BASE,
        urlChatId: "chat-a",
        currentChatId: "chat-a",
        selectedAgent: "agent-b",
        currentChatDatasource: "agent-b",
      })
    ).toEqual({ kind: "noop" });
  });

  it("does NOT revert an explicit agent choice while navigating home with a stale chat", () => {
    // Regression: user clicked agent-b; navigate("/") cleared the URL chat but
    // currentChatId still holds the previous chat (which used agent-a) for a
    // render. The stale chat must not override the fresh choice.
    expect(
      resolveSelectedAgent({
        ...BASE,
        urlChatId: undefined,
        currentChatId: "chat-a",
        selectedAgent: "agent-b",
        currentChatDatasource: "agent-a",
      })
    ).toEqual({ kind: "noop" });
  });

  it("keeps a valid cached selection on the home route", () => {
    expect(
      resolveSelectedAgent({ ...BASE, selectedAgent: "agent-b" })
    ).toEqual({ kind: "noop" });
  });

  it("falls back to the first available agent when selection is invalid", () => {
    expect(
      resolveSelectedAgent({ ...BASE, selectedAgent: "removed-agent" })
    ).toEqual({ kind: "select", agent: "agent-a" });
  });

  it("falls back to the first available agent when nothing is selected", () => {
    expect(resolveSelectedAgent({ ...BASE, selectedAgent: null })).toEqual({
      kind: "select",
      agent: "agent-a",
    });
  });

  it("ignores a chat datasource that is no longer an available agent", () => {
    expect(
      resolveSelectedAgent({
        ...BASE,
        urlChatId: "chat-a",
        currentChatId: "chat-a",
        selectedAgent: "agent-a",
        currentChatDatasource: "removed-agent",
      })
    ).toEqual({ kind: "noop" });
  });

  it("does nothing when there are no available agents", () => {
    expect(
      resolveSelectedAgent({ ...BASE, availableAgents: [], selectedAgent: null })
    ).toEqual({ kind: "noop" });
  });
});
