import { describe, it, expect } from "vitest";
import {
  COMPOSER_REFERENCES_MARKER,
  addReference,
  removeReference,
  referenceToken,
  appendReferenceToken,
  filterReferencesInText,
  segmentContentWithReferences,
  composeQuestionWithReferences,
  parseComposerReferences,
  getUserVisibleContent,
  type ComposerReference,
} from "./composerReferences";

const DOC_A: ComposerReference = {
  kind: "document",
  id: "1bb01250-768e-4878-8efd-63bf7ff2ab86",
  label: "15.pdf",
  sourcePluginId: "search",
};

const DOC_B: ComposerReference = {
  kind: "document",
  id: "96f77ab2-6650-4185-9190-09c252cf2e54",
  label: "contract.pdf",
  sourcePluginId: "search",
};

describe("addReference / removeReference", () => {
  it("appends a new reference", () => {
    expect(addReference([], DOC_A)).toEqual([DOC_A]);
  });

  it("deduplicates by kind + sourcePluginId + id", () => {
    const once = addReference([], DOC_A);
    const twice = addReference(once, { ...DOC_A, label: "renamed.pdf" });
    expect(twice).toBe(once);
  });

  it("keeps references with same id but different plugin", () => {
    const other = { ...DOC_A, sourcePluginId: "other" };
    expect(addReference([DOC_A], other)).toHaveLength(2);
  });

  it("removes only the matching reference", () => {
    expect(removeReference([DOC_A, DOC_B], DOC_A)).toEqual([DOC_B]);
  });
});

describe("referenceToken / appendReferenceToken", () => {
  it("builds an inline token from the label", () => {
    expect(referenceToken(DOC_A)).toBe("@[15.pdf]");
  });

  it("strips brackets from the label to keep the token parseable", () => {
    const tricky = { ...DOC_A, label: "we[ird].pdf" };
    expect(referenceToken(tricky)).toBe("@[weird.pdf]");
  });

  it("appends the token with spacing", () => {
    expect(appendReferenceToken("show", DOC_A)).toBe("show @[15.pdf] ");
    expect(appendReferenceToken("", DOC_A)).toBe("@[15.pdf] ");
  });

  it("does not duplicate an existing token", () => {
    const text = "show @[15.pdf] ";
    expect(appendReferenceToken(text, DOC_A)).toBe(text);
  });
});

describe("filterReferencesInText", () => {
  it("keeps only references whose token is present", () => {
    const text = "compare @[15.pdf] with something";
    expect(filterReferencesInText(text, [DOC_A, DOC_B])).toEqual([DOC_A]);
  });
});

describe("segmentContentWithReferences", () => {
  it("returns a single text segment without references", () => {
    expect(segmentContentWithReferences("plain", [])).toEqual([
      { text: "plain" },
    ]);
  });

  it("splits text around known tokens", () => {
    const content = "show @[15.pdf] and @[contract.pdf] now";
    const segments = segmentContentWithReferences(content, [DOC_A, DOC_B]);
    expect(segments).toEqual([
      { text: "show " },
      { text: "@[15.pdf]", reference: DOC_A },
      { text: " and " },
      { text: "@[contract.pdf]", reference: DOC_B },
      { text: " now" },
    ]);
  });

  it("leaves unknown tokens as plain text", () => {
    const content = "show @[unknown.pdf] now";
    expect(segmentContentWithReferences(content, [DOC_A])).toEqual([
      { text: content },
    ]);
  });
});

describe("composeQuestionWithReferences", () => {
  it("returns trimmed text unchanged without references", () => {
    expect(composeQuestionWithReferences("  hello  ", [])).toBe("hello");
  });

  it("appends marker and JSON payload", () => {
    const composed = composeQuestionWithReferences("summarize this", [DOC_A]);
    expect(composed.startsWith("summarize this")).toBe(true);
    expect(composed).toContain(COMPOSER_REFERENCES_MARKER);
    expect(composed).toContain(DOC_A.id);
  });

  it("round-trips through parseComposerReferences", () => {
    const composed = composeQuestionWithReferences("compare", [DOC_A, DOC_B]);
    expect(parseComposerReferences(composed)).toEqual([DOC_A, DOC_B]);
  });
});

describe("parseComposerReferences", () => {
  it("returns empty list when marker is absent", () => {
    expect(parseComposerReferences("plain question")).toEqual([]);
  });

  it("returns empty list for malformed JSON", () => {
    const content = `question\n\n${COMPOSER_REFERENCES_MARKER}\n{not json`;
    expect(parseComposerReferences(content)).toEqual([]);
  });

  it("returns empty list for unknown payload shape", () => {
    const content = `q\n\n${COMPOSER_REFERENCES_MARKER}\n${JSON.stringify({ foo: 1 })}`;
    expect(parseComposerReferences(content)).toEqual([]);
  });

  it("filters out invalid entries but keeps valid ones", () => {
    const payload = JSON.stringify({
      references: [DOC_A, { kind: "document" }, "junk", null],
    });
    const content = `q\n\n${COMPOSER_REFERENCES_MARKER}\n${payload}`;
    expect(parseComposerReferences(content)).toEqual([DOC_A]);
  });
});

describe("getUserVisibleContent", () => {
  it("returns full content without any marker", () => {
    expect(getUserVisibleContent("plain question")).toBe("plain question");
  });

  it("strips COMPOSER_REFERENCES_V1 payload", () => {
    const composed = composeQuestionWithReferences("visible part", [DOC_A]);
    expect(getUserVisibleContent(composed)).toBe("visible part");
  });

  it("strips WIDGET_MAKE_CHOICES_ANSWERS payload (existing behaviour)", () => {
    const content = `- Q: A\n\nWIDGET_MAKE_CHOICES_ANSWERS\n{"answers": []}`;
    expect(getUserVisibleContent(content)).toBe("- Q: A");
  });

  it("cuts at the earliest marker when both are present", () => {
    const content = `text\n\n${COMPOSER_REFERENCES_MARKER}\n{"references":[]}\nWIDGET_MAKE_CHOICES_ANSWERS\n{}`;
    expect(getUserVisibleContent(content)).toBe("text");
  });
});
