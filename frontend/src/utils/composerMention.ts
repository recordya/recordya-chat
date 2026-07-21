/**
 * Detection of "@" mention tokens in the composer textarea.
 *
 * A mention is an "@" that starts a word (preceded by start-of-text or
 * whitespace) followed by the query typed so far, up to the caret. The query
 * itself cannot contain whitespace — typing a space closes the mention.
 */

export interface MentionQuery {
  /** Query text between "@" and the caret (may be empty). */
  query: string;
  /** Index of the "@" character in the text. */
  start: number;
  /** Caret index; end of the mention token (exclusive). */
  end: number;
}

const MAX_MENTION_QUERY_LENGTH = 100;

/** Returns the active mention at the caret, or null when there is none. */
export function detectMention(text: string, caret: number): MentionQuery | null {
  if (caret < 1 || caret > text.length) {
    return null;
  }
  const beforeCaret = text.slice(0, caret);
  const atIndex = beforeCaret.lastIndexOf("@");
  if (atIndex === -1) {
    return null;
  }
  if (atIndex > 0 && !/\s/.test(beforeCaret[atIndex - 1])) {
    return null;
  }
  const query = beforeCaret.slice(atIndex + 1);
  if (/\s/.test(query) || query.length > MAX_MENTION_QUERY_LENGTH) {
    return null;
  }
  // "@[" starts an already-inserted reference token (see referenceToken) —
  // don't reopen the popover when the caret is inside one.
  if (query.startsWith("[")) {
    return null;
  }
  return { query, start: atIndex, end: caret };
}

/**
 * Replaces the mention token with the given inline replacement (used after
 * picking a suggestion, which inserts a reference token such as "@[15.pdf]").
 * Ensures a single space after the replacement so typing can continue.
 */
export function replaceMentionToken(
  text: string,
  mention: MentionQuery,
  replacement: string,
): string {
  const before = text.slice(0, mention.start);
  const after = text.slice(mention.end);
  const spacer = after.startsWith(" ") ? "" : " ";
  return `${before}${replacement}${spacer}${after}`;
}
