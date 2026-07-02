import type { Chat } from "@/hooks/use-chat-history";

export function getNextChatIndexAfterDelete(
  deletedIndex: number,
  remainingCount: number
): number | null {
  if (remainingCount === 0) return null;
  return Math.min(deletedIndex, remainingCount - 1);
}

export function getNextChatIdAfterDelete(
  chats: Chat[],
  deletedId: string
): string | null {
  const deletedIndex = chats.findIndex((chat) => chat.id === deletedId);
  if (deletedIndex === -1) return null;

  const remainingChats = chats.filter((chat) => chat.id !== deletedId);
  const nextIndex = getNextChatIndexAfterDelete(deletedIndex, remainingChats.length);
  if (nextIndex === null) return null;

  return remainingChats[nextIndex]?.id ?? null;
}
