import { describe, it, expect } from "vitest";
import { isPluginEnabled, isPluginInitialized, resetPluginInitialization } from "./registry";

describe("isPluginEnabled", () => {
  it("returns false when enabled is false", () => {
    const manifest = `id: "my_plugin"\nname: "My Plugin"\nenabled: false`;
    expect(isPluginEnabled(manifest)).toBe(false);
  });

  it("returns true when enabled is true", () => {
    const manifest = `id: "my_plugin"\nname: "My Plugin"\nenabled: true`;
    expect(isPluginEnabled(manifest)).toBe(true);
  });

  it("returns true when enabled key is missing", () => {
    const manifest = `id: "my_plugin"\nname: "My Plugin"`;
    expect(isPluginEnabled(manifest)).toBe(true);
  });

  it("returns true for empty manifest", () => {
    expect(isPluginEnabled("")).toBe(true);
  });

  it("handles enabled: False (capitalized)", () => {
    const manifest = `id: "test"\nenabled: False`;
    expect(isPluginEnabled(manifest)).toBe(false);
  });

  it("handles enabled: FALSE (all caps)", () => {
    const manifest = `id: "test"\nenabled: FALSE`;
    expect(isPluginEnabled(manifest)).toBe(false);
  });

  it("handles enabled: True (capitalized)", () => {
    const manifest = `id: "test"\nenabled: True`;
    expect(isPluginEnabled(manifest)).toBe(true);
  });

  it("ignores enabled inside a comment", () => {
    const manifest = `id: "test"\nname: "Test" # enabled: false`;
    expect(isPluginEnabled(manifest)).toBe(true);
  });

  it("handles enabled with trailing comment", () => {
    const manifest = `id: "test"\nenabled: false # disabled for testing`;
    expect(isPluginEnabled(manifest)).toBe(false);
  });

  it("handles extra whitespace around value", () => {
    const manifest = `id: "test"\nenabled:   false  `;
    expect(isPluginEnabled(manifest)).toBe(false);
  });

  it("handles Windows line endings (\\r\\n)", () => {
    const manifest = `id: "test"\r\nenabled: false\r\nname: "Test"`;
    expect(isPluginEnabled(manifest)).toBe(false);
  });

  it("matches indented enabled (trim strips leading spaces)", () => {
    const manifest = `id: "test"\nsome_block:\n  enabled: false`;
    // Note: isPluginEnabled trims lines before matching, so indented
    // "enabled:" keys also match. This is acceptable because plugin
    // manifests only use top-level "enabled:" in practice.
    expect(isPluginEnabled(manifest)).toBe(false);
  });
});

describe("isPluginInitialized", () => {
  it("returns false for a plugin that was not initialized", () => {
    resetPluginInitialization();
    expect(isPluginInitialized("any_plugin")).toBe(false);
  });
});
