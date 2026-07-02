import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { Slot } from "./Slot";
import { slotRegistry } from "@/plugins/SlotRegistry";

const SLOT_NAME = "detail.panel" as const;

afterEach(() => {
  slotRegistry.unregister(SLOT_NAME, "slot-test-a");
  slotRegistry.unregister(SLOT_NAME, "slot-test-b");
});

describe("Slot", () => {
  it("renders registered components in order", () => {
    slotRegistry.register(SLOT_NAME, {
      pluginId: "slot-test-a",
      order: 10,
      component: () => <div>first</div>,
    });
    slotRegistry.register(SLOT_NAME, {
      pluginId: "slot-test-b",
      order: 20,
      component: () => <div>second</div>,
    });

    const html = renderToStaticMarkup(
      <Slot name={SLOT_NAME} context={{ agentId: "slot-test-plugin" }} />
    );

    expect(html).toContain("first");
    expect(html).toContain("second");
    expect(html.indexOf("first")).toBeLessThan(html.indexOf("second"));
  });

  it("returns null when no components registered", () => {
    const html = renderToStaticMarkup(
      <Slot name={SLOT_NAME} context={{ agentId: "slot-test-plugin" }} />
    );

    expect(html).toBe("");
  });

  it("respects condition filter", () => {
    slotRegistry.register(SLOT_NAME, {
      pluginId: "slot-test-a",
      component: () => <div>visible</div>,
      condition: (ctx) => ctx.agentId === "match",
    });

    const hidden = renderToStaticMarkup(
      <Slot name={SLOT_NAME} context={{ agentId: "no-match" }} />
    );
    expect(hidden).toBe("");

    const shown = renderToStaticMarkup(
      <Slot name={SLOT_NAME} context={{ agentId: "match" }} />
    );
    expect(shown).toContain("visible");
  });
});
