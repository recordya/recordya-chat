import { useLayoutEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import {
  segmentContentWithReferences,
  type ComposerReference,
} from "@/utils/composerReferences";

/**
 * Composer input rendering inline reference tokens ("@[15.pdf]") as chips.
 *
 * A textarea cannot host inline elements, so this is a contentEditable div.
 * The plain text with tokens stays the source of truth: chips are atomic
 * spans (contentEditable=false) carrying their token in a data attribute,
 * and the DOM serializes back to exactly that text. Backspace on a chip
 * removes it whole (native atomic-element behaviour).
 */

interface ComposerInputProps {
  value: string;
  references: ComposerReference[];
  onChange: (value: string) => void;
  /** Fired on every caret-affecting interaction with the serialized text and caret offset. */
  onCaretUpdate: (text: string, caret: number) => void;
  onKeyDown: (event: React.KeyboardEvent) => void;
  onBlur?: () => void;
  placeholder: string;
  disabled?: boolean;
  maxLength: number;
}

const FILE_ICON_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-3 w-3 flex-shrink-0 text-muted-foreground" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>';

/** Serializes editor DOM back to plain text with reference tokens. */
function serializeNode(node: Node): string {
  let out = "";
  node.childNodes.forEach((child) => {
    if (child.nodeType === Node.TEXT_NODE) {
      out += child.textContent ?? "";
      return;
    }
    if (!(child instanceof HTMLElement)) {
      return;
    }
    if (child.dataset.referenceToken) {
      out += child.dataset.referenceToken;
      return;
    }
    if (child.tagName === "BR") {
      out += "\n";
      return;
    }
    out += serializeNode(child);
  });
  return out;
}

function buildChip(token: string, label: string): HTMLSpanElement {
  const chip = document.createElement("span");
  chip.contentEditable = "false";
  chip.dataset.referenceToken = token;
  chip.className =
    "inline-flex items-center gap-1 align-middle rounded-md border border-border bg-background px-1.5 py-0.5 mx-0.5 text-xs text-foreground max-w-[16rem] select-none";
  chip.innerHTML = FILE_ICON_SVG;
  const text = document.createElement("span");
  text.className = "truncate";
  text.textContent = label;
  chip.title = label;
  chip.appendChild(text);
  return chip;
}

function rebuildEditor(
  root: HTMLElement,
  value: string,
  references: ComposerReference[],
): void {
  root.textContent = "";
  for (const segment of segmentContentWithReferences(value, references)) {
    if (segment.reference) {
      root.appendChild(buildChip(segment.text, segment.reference.label));
    } else if (segment.text) {
      root.appendChild(document.createTextNode(segment.text));
    }
  }
}

/** Caret offset within the serialized text (chips count as their token). */
function getCaretOffset(root: HTMLElement): number {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    return serializeNode(root).length;
  }
  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer)) {
    return serializeNode(root).length;
  }
  const prefix = range.cloneRange();
  prefix.selectNodeContents(root);
  prefix.setEnd(range.startContainer, range.startOffset);
  return serializeNode(prefix.cloneContents()).length;
}

function placeCaretAtEnd(root: HTMLElement): void {
  const selection = window.getSelection();
  if (!selection) {
    return;
  }
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

export function ComposerInput({
  value,
  references,
  onChange,
  onCaretUpdate,
  onKeyDown,
  onBlur,
  placeholder,
  disabled = false,
  maxLength,
}: ComposerInputProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  // Rebuild the DOM only when the external value diverges from what the
  // editor already contains (e.g. a chip was inserted); typing round-trips
  // to the same text, keeping the caret untouched.
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root || serializeNode(root) === value) {
      return;
    }
    rebuildEditor(root, value, references);
    if (document.activeElement === root) {
      placeCaretAtEnd(root);
    }
  }, [value, references]);

  const emitCaret = () => {
    const root = rootRef.current;
    if (root) {
      onCaretUpdate(serializeNode(root), getCaretOffset(root));
    }
  };

  return (
    <div className="relative flex-1">
      {value.length === 0 && (
        <span className="absolute inset-0 pointer-events-none text-sm py-1.5 text-muted-foreground/60">
          {placeholder}
        </span>
      )}
      <div
        ref={rootRef}
        role="textbox"
        aria-multiline="true"
        aria-label={placeholder}
        contentEditable={!disabled}
        suppressContentEditableWarning
        spellCheck={false}
        className={cn(
          "min-h-8 max-h-40 overflow-y-auto py-1.5 text-sm outline-none whitespace-pre-wrap break-words",
          disabled && "opacity-50",
        )}
        onInput={() => {
          const root = rootRef.current;
          if (!root) {
            return;
          }
          let text = serializeNode(root);
          // An emptied contentEditable often keeps a lone <br>.
          if (text === "\n") {
            text = "";
            root.textContent = "";
          }
          onChange(text.length > maxLength ? text.slice(0, maxLength) : text);
          emitCaret();
        }}
        onKeyDown={(event) => {
          onKeyDown(event);
          if (event.defaultPrevented) {
            return;
          }
          if (event.key === "Enter" && event.shiftKey) {
            event.preventDefault();
            document.execCommand("insertText", false, "\n");
          }
        }}
        onKeyUp={emitCaret}
        onClick={emitCaret}
        onPaste={(event) => {
          event.preventDefault();
          const text = event.clipboardData.getData("text/plain");
          if (text) {
            document.execCommand("insertText", false, text);
          }
        }}
        onBlur={onBlur}
      />
    </div>
  );
}
