/**
 * Structured composer references ("chips") attached to a user message.
 *
 * A reference points at an entity (currently a document) by a stable
 * identifier. On submit the references are serialized into a machine-readable
 * payload appended after the visible question text, following the same
 * pattern as WIDGET_MAKE_CHOICES_ANSWERS (see ChoicesWidget). The UI hides
 * the payload when rendering user messages; retry and history replay keep it
 * because it lives inside the persisted message content.
 */

export const COMPOSER_REFERENCES_MARKER = "COMPOSER_REFERENCES_V1";

/** Marker used by ChoicesWidget; kept here so user-visible stripping covers both. */
export const WIDGET_MAKE_CHOICES_MARKER = "WIDGET_MAKE_CHOICES_ANSWERS";

const MACHINE_PAYLOAD_MARKERS = [
  COMPOSER_REFERENCES_MARKER,
  WIDGET_MAKE_CHOICES_MARKER,
];

export interface ComposerReference {
  /** Reference kind, e.g. "document". */
  kind: string;
  /** Stable identifier of the referenced entity (e.g. document UUID). */
  id: string;
  /** Human-readable label shown on the chip; never used as a lookup key. */
  label: string;
  /** Plugin that produced the reference, e.g. "search". */
  sourcePluginId?: string;
}

/** Identity key used for deduplication. */
export function referenceKey(reference: ComposerReference): string {
  return `${reference.kind}::${reference.sourcePluginId ?? ""}::${reference.id}`;
}

/** Matches inline reference tokens, e.g. "@[15.pdf]". */
const REFERENCE_TOKEN_PATTERN = /@\[[^\]]*\]/g;

function sanitizeTokenLabel(label: string): string {
  return label.replace(/[[\]]/g, "").trim();
}

/**
 * Inline token representing a reference inside the composer text,
 * e.g. "@[15.pdf]". The token is plain text in the textarea; message
 * rendering replaces it with a chip.
 */
export function referenceToken(reference: ComposerReference): string {
  return `@[${sanitizeTokenLabel(reference.label)}]`;
}

/** Appends the reference token to the text unless it is already present. */
export function appendReferenceToken(
  text: string,
  reference: ComposerReference,
): string {
  const token = referenceToken(reference);
  if (text.includes(token)) {
    return text;
  }
  if (!text) {
    return `${token} `;
  }
  return `${text.endsWith(" ") ? text : `${text} `}${token} `;
}

/**
 * Keeps only references whose inline token is still present in the text —
 * deleting the token from the composer detaches the reference.
 */
export function filterReferencesInText(
  text: string,
  references: ComposerReference[],
): ComposerReference[] {
  return references.filter((reference) =>
    text.includes(referenceToken(reference)),
  );
}

export interface ContentSegment {
  text: string;
  /** Present when the segment is an inline reference token. */
  reference?: ComposerReference;
}

/**
 * Splits visible content into plain-text segments and inline reference
 * segments. Tokens that do not match any known reference stay as text.
 */
export function segmentContentWithReferences(
  content: string,
  references: ComposerReference[],
): ContentSegment[] {
  if (references.length === 0 || !content.includes("@[")) {
    return [{ text: content }];
  }
  const byToken = new Map(
    references.map((reference) => [referenceToken(reference), reference]),
  );
  const segments: ContentSegment[] = [];
  let lastIndex = 0;
  for (const match of content.matchAll(REFERENCE_TOKEN_PATTERN)) {
    const index = match.index ?? 0;
    const token = match[0];
    const reference = byToken.get(token);
    if (!reference) {
      continue;
    }
    if (index > lastIndex) {
      segments.push({ text: content.slice(lastIndex, index) });
    }
    segments.push({ text: token, reference });
    lastIndex = index + token.length;
  }
  if (lastIndex < content.length) {
    segments.push({ text: content.slice(lastIndex) });
  }
  return segments.length > 0 ? segments : [{ text: content }];
}

/** Returns a new list with the reference appended unless an equal one exists. */
export function addReference(
  references: ComposerReference[],
  reference: ComposerReference,
): ComposerReference[] {
  const key = referenceKey(reference);
  if (references.some((existing) => referenceKey(existing) === key)) {
    return references;
  }
  return [...references, reference];
}

/** Returns a new list without the given reference. */
export function removeReference(
  references: ComposerReference[],
  reference: ComposerReference,
): ComposerReference[] {
  const key = referenceKey(reference);
  return references.filter((existing) => referenceKey(existing) !== key);
}

/**
 * Combines the visible question text with the machine payload carrying the
 * references. Returns the text unchanged when there are no references.
 */
export function composeQuestionWithReferences(
  text: string,
  references: ComposerReference[],
): string {
  const trimmed = text.trim();
  if (references.length === 0) {
    return trimmed;
  }
  const payload = JSON.stringify({ references });
  return `${trimmed}\n\n${COMPOSER_REFERENCES_MARKER}\n${payload}`;
}

function isValidReference(value: unknown): value is ComposerReference {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.kind === "string" &&
    record.kind.length > 0 &&
    typeof record.id === "string" &&
    record.id.length > 0 &&
    typeof record.label === "string" &&
    (record.sourcePluginId === undefined ||
      typeof record.sourcePluginId === "string")
  );
}

/**
 * Extracts references from a message that carries a COMPOSER_REFERENCES_V1
 * payload. Returns an empty list for missing, malformed or unknown payloads —
 * never throws.
 */
export function parseComposerReferences(content: string): ComposerReference[] {
  const markerIndex = content.indexOf(COMPOSER_REFERENCES_MARKER);
  if (markerIndex === -1) {
    return [];
  }
  const raw = content.slice(markerIndex + COMPOSER_REFERENCES_MARKER.length);
  try {
    const parsed: unknown = JSON.parse(raw.trim());
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return [];
    }
    const references = (parsed as Record<string, unknown>).references;
    if (!Array.isArray(references)) {
      return [];
    }
    return references.filter(isValidReference);
  } catch {
    return [];
  }
}

/**
 * Strips any machine payload (references, widget answers) from a user
 * message, returning only the text meant for display.
 */
export function getUserVisibleContent(content: string): string {
  let cutIndex = content.length;
  for (const marker of MACHINE_PAYLOAD_MARKERS) {
    const markerIndex = content.indexOf(marker);
    if (markerIndex !== -1 && markerIndex < cutIndex) {
      cutIndex = markerIndex;
    }
  }
  return content.slice(0, cutIndex).trimEnd();
}
