export type ChatRouteAction =
  | { kind: "noop" }
  | { kind: "load"; chatId: string }
  | { kind: "redirect-home" }
  | { kind: "start-new" };

export interface ChatRouteSyncInput {
  urlChatId: string | undefined;
  currentChatId: string | null;
  chatsLoaded: boolean;
  knownChatIds: ReadonlySet<string>;
}

export function resolveChatRouteAction(input: ChatRouteSyncInput): ChatRouteAction {
  const { urlChatId, currentChatId, chatsLoaded, knownChatIds } = input;
  if (!chatsLoaded) return { kind: "noop" };
  if (urlChatId) {
    if (urlChatId === currentChatId) return { kind: "noop" };
    if (knownChatIds.has(urlChatId)) return { kind: "load", chatId: urlChatId };
    return { kind: "redirect-home" };
  }
  if (currentChatId !== null) return { kind: "start-new" };
  return { kind: "noop" };
}
