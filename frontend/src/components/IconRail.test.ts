import { describe, it, expect } from "vitest";
import { LayoutGrid, ClipboardList, Mic, ChartBar } from "lucide-react";
import { resolveLucideIcon } from "./IconRail";

describe("resolveLucideIcon", () => {
  it("resolves clipboard-list to ClipboardList", () => {
    expect(resolveLucideIcon("clipboard-list")).toBe(ClipboardList);
  });

  it("resolves mic to Mic (single word)", () => {
    expect(resolveLucideIcon("mic")).toBe(Mic);
  });

  it("resolves chart-bar to ChartBar (multi-segment)", () => {
    expect(resolveLucideIcon("chart-bar")).toBe(ChartBar);
  });

  it("resolves layout-grid to LayoutGrid", () => {
    expect(resolveLucideIcon("layout-grid")).toBe(LayoutGrid);
  });

  it("returns LayoutGrid fallback for unknown icon name", () => {
    expect(resolveLucideIcon("nonexistent-icon-xyz")).toBe(LayoutGrid);
  });

  it("returns LayoutGrid fallback for undefined", () => {
    expect(resolveLucideIcon(undefined)).toBe(LayoutGrid);
  });

  it("returns LayoutGrid fallback for empty string", () => {
    expect(resolveLucideIcon("")).toBe(LayoutGrid);
  });
});
