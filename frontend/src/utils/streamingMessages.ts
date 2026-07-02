import type { Message } from "@/components/ChatMessage";

export function upsertMessage(messages: Message[], nextMessage: Message): Message[] {
  const existingIndex = messages.findIndex((message) => message.id === nextMessage.id);
  if (existingIndex === -1) {
    return [...messages, nextMessage];
  }

  return messages.map((message) => (
    message.id === nextMessage.id ? nextMessage : message
  ));
}

export function mergeMessage(messages: Message[], nextMessage: Message): Message[] {
  const existingIndex = messages.findIndex((message) => message.id === nextMessage.id);
  if (existingIndex === -1) {
    return [...messages, nextMessage];
  }

  return messages.map((message) => (
    message.id === nextMessage.id ? { ...message, ...nextMessage } : message
  ));
}

export function removeMessage(messages: Message[], messageId: string): Message[] {
  return messages.filter((message) => message.id !== messageId);
}
