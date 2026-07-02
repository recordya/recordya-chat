/**
 * Pure helper functions for chat isolation logic.
 *
 * When a streaming request is in-flight and the user switches to a different
 * chat, the response must NOT be appended to the UI message list of the new
 * chat.  These helpers encapsulate the decision so it can be unit-tested
 * without rendering React components.
 */

/**
 * Should the assistant response be appended to the visible message list?
 *
 * Returns `true` only when the user is still viewing the same chat that
 * initiated the request.  The response is always persisted to the DB
 * regardless of this check.
 *
 * @param currentChatId - The chat ID currently displayed in the UI.
 * @param requestChatId - The chat ID that owns the in-flight request.
 */
export function shouldUpdateMessages(
  currentChatId: string | null,
  requestChatId: string,
): boolean {
  return currentChatId === requestChatId;
}

/**
 * Should the loading / streaming-status spinner be visible?
 *
 * The spinner should only appear when:
 * 1. A request is globally in-flight (`isProcessing`), AND
 * 2. The user is viewing the chat that owns that request.
 *
 * @param isProcessing    - Global flag: is any request in-flight?
 * @param processingChatId - The chat ID that owns the in-flight request (null when idle).
 * @param currentChatId    - The chat ID currently displayed in the UI.
 */
export function shouldShowProcessing(
  isProcessing: boolean,
  processingChatId: string | null,
  currentChatId: string | null,
): boolean {
  return isProcessing && processingChatId !== null && processingChatId === currentChatId;
}

/**
 * Result of computing a retry action from a message list.
 */
export interface RetryAction {
  /** The user question to re-submit. */
  question: string;
  /** Message IDs to remove before re-submitting (error + original user message). */
  removeIds: [string, string];
}

/**
 * Given a list of messages and the ID of an error/assistant message the user
 * wants to retry, compute the IDs to remove and the question to re-send.
 *
 * Returns `null` when the retry cannot be performed (e.g. no preceding user
 * message found).
 *
 * @param messages       - Current message list.
 * @param errorMessageId - ID of the error (assistant) message to retry.
 */
export function computeRetryAction(
  messages: ReadonlyArray<{ id: string; role: string; content: string }>,
  errorMessageId: string,
): RetryAction | null {
  const errorIndex = messages.findIndex((m) => m.id === errorMessageId);
  if (errorIndex < 1) return null;

  for (let i = errorIndex - 1; i >= 0; i--) {
    if (messages[i].role === "user") {
      return {
        question: messages[i].content,
        removeIds: [errorMessageId, messages[i].id],
      };
    }
  }
  return null;
}

