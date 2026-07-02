export type AgentSelectionAction =
  | { kind: "noop" }
  | { kind: "select"; agent: string };

export interface AgentSelectionInput {
  agentsLoaded: boolean;
  chatsLoaded: boolean;
  urlChatId: string | undefined;
  currentChatId: string | null;
  selectedAgent: string | null;
  /** Available agent names, in priority order (index 0 = first available). */
  availableAgents: readonly string[];
  /** datasource of the currently open chat, if any. */
  currentChatDatasource: string | null;
}

/**
 * Decide which agent should be selected.
 *
 * A chat's datasource is authoritative only when the URL actually points to
 * that chat (`urlChatId === currentChatId`). On the home route the URL has no
 * chat id, yet `currentChatId` may still hold the previous chat for a render
 * or two while it clears — that stale chat must not override an explicit agent
 * choice the user just made. Otherwise prefer the cached/explicit selection and
 * fall back to the first available agent only when nothing valid remains.
 */
export function resolveSelectedAgent(input: AgentSelectionInput): AgentSelectionAction {
  const {
    agentsLoaded,
    chatsLoaded,
    urlChatId,
    currentChatId,
    selectedAgent,
    availableAgents,
    currentChatDatasource,
  } = input;

  if (!agentsLoaded || !chatsLoaded) return { kind: "noop" };
  // Wait for a deep-linked chat to load before deciding on the agent.
  if (urlChatId && urlChatId !== currentChatId) return { kind: "noop" };

  const chatIsAuthoritative = currentChatId !== null && urlChatId === currentChatId;
  if (
    chatIsAuthoritative &&
    currentChatDatasource &&
    availableAgents.includes(currentChatDatasource)
  ) {
    return selectedAgent === currentChatDatasource
      ? { kind: "noop" }
      : { kind: "select", agent: currentChatDatasource };
  }

  const isSelectedValid = selectedAgent !== null && availableAgents.includes(selectedAgent);
  if (!isSelectedValid && availableAgents.length > 0) {
    return { kind: "select", agent: availableAgents[0] };
  }
  return { kind: "noop" };
}
