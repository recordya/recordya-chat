import { afterEach, describe, it, expect } from "vitest";
import { convertBulletsToMarkdown, stripMarkdownTables } from "@/utils/markdown";
import { createPluginSDK } from "@/plugins/sdk";
import { transformRegistry, type TransformContext } from "@/plugins/TransformRegistry";

describe("convertBulletsToMarkdown", () => {
  it("converts bullet points to markdown list with each item on new line", () => {
    const input = "Znaleziono 5 audiobooków:\n• Dominują **thrillery**\n• Główne platformy: **Storytel**";
    const expected = "Znaleziono 5 audiobooków:\n- Dominują **thrillery**\n- Główne platformy: **Storytel**";
    expect(convertBulletsToMarkdown(input)).toBe(expected);
  });

  it("handles bullets not on new line (preserves inline format)", () => {
    // Current implementation preserves original spacing - LLM is instructed to put bullets on new lines
    const input = "Wyniki: • Item 1 • Item 2";
    const result = convertBulletsToMarkdown(input);
    // Mid-line bullets are preserved as-is (not at start of line, so not converted)
    expect(result).toBe("Wyniki: • Item 1 • Item 2");
  });

  it("preserves text without bullets", () => {
    const input = "Zwykły tekst bez punktów.";
    expect(convertBulletsToMarkdown(input)).toBe(input);
  });

  it("handles middle dot (·) as well", () => {
    const input = "Lista:\n· Punkt jeden\n· Punkt dwa";
    const expected = "Lista:\n- Punkt jeden\n- Punkt dwa";
    expect(convertBulletsToMarkdown(input)).toBe(expected);
  });
});

describe("plugin-driven markdown table stripping via transforms", () => {
  const TABLE = "Summary:\n| Col A | Col B |\n| --- | --- |\n| 1 | 2 |";
  const PLUGIN_ID = "table-stripper-test";

  // Mirrors how plugins opt in: strip tables only for their own messages
  // that also carry rendered results.
  const registerStrippingPlugin = (): void => {
    const sdk = createPluginSDK(PLUGIN_ID);
    sdk.transform((text) => stripMarkdownTables(text), {
      condition: (_text, context) =>
        context?.sourcePluginId === PLUGIN_ID && context?.hasResults === true,
    });
  };

  afterEach(() => {
    transformRegistry.unregister(PLUGIN_ID);
  });

  it("strips the table for the opted-in plugin when results are present", () => {
    registerStrippingPlugin();
    const context: TransformContext = { sourcePluginId: PLUGIN_ID, hasResults: true };

    const prepared = transformRegistry.transform(TABLE, context);
    expect(prepared).not.toContain("| Col A | Col B |");
    expect(prepared).toContain("Summary:");
  });

  it("keeps the table when the same plugin has no results", () => {
    registerStrippingPlugin();
    const context: TransformContext = { sourcePluginId: PLUGIN_ID, hasResults: false };

    expect(transformRegistry.transform(TABLE, context)).toBe(TABLE);
  });

  it("never strips tables authored by a different plugin", () => {
    registerStrippingPlugin();
    const context: TransformContext = { sourcePluginId: "search", hasResults: true };

    expect(transformRegistry.transform(TABLE, context)).toBe(TABLE);
  });

  it("renders tables by default when no plugin opts in", () => {
    const context: TransformContext = { sourcePluginId: "search", hasResults: true };

    expect(transformRegistry.transform(TABLE, context)).toBe(TABLE);
  });
});
