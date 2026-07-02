import { describe, it, expect, beforeEach } from "vitest";
import { createElement } from "react";
import {
  toolRendererRegistry,
  type ToolRenderContext,
} from "./ToolRendererRegistry";

function makeContext(overrides: Partial<ToolRenderContext> = {}): ToolRenderContext {
  return {
    toolId: "tool-1",
    toolName: "test_tool",
    status: "done",
    arguments: {},
    result: {},
    ...overrides,
  };
}

describe("ToolRendererRegistry", () => {
  beforeEach(() => {
    toolRendererRegistry.unregisterPlugin("plugin_a");
    toolRendererRegistry.unregisterPlugin("plugin_b");
  });

  it("returns default action when no renderer is registered", () => {
    const decision = toolRendererRegistry.resolve(makeContext(), "result");
    expect(decision.action).toBe("default");
  });

  it("renders custom node when matching renderer exists", () => {
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "test_tool",
      target: "result",
      priority: 100,
      decide: () => ({
        action: "render",
        node: createElement("div", null, "custom"),
      }),
    });

    const decision = toolRendererRegistry.resolve(
      makeContext({ sourcePluginId: "plugin_a" }),
      "result"
    );
    expect(decision.action).toBe("render");
    expect(decision.node).toBeDefined();
  });

  it("returns hide when renderer decides to hide", () => {
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "test_tool",
      target: "arguments",
      priority: 100,
      decide: () => ({ action: "hide" }),
    });

    const decision = toolRendererRegistry.resolve(
      makeContext({ sourcePluginId: "plugin_a" }),
      "arguments"
    );
    expect(decision.action).toBe("hide");
  });

  it("ignores renderers for a different target", () => {
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "test_tool",
      target: "arguments",
      priority: 100,
      decide: () => ({ action: "hide" }),
    });

    const decision = toolRendererRegistry.resolve(
      makeContext({ sourcePluginId: "plugin_a" }),
      "result"
    );
    expect(decision.action).toBe("default");
  });

  it("ignores renderers for a different toolName", () => {
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "other_tool",
      target: "result",
      priority: 100,
      decide: () => ({ action: "hide" }),
    });

    const decision = toolRendererRegistry.resolve(
      makeContext({ sourcePluginId: "plugin_a" }),
      "result"
    );
    expect(decision.action).toBe("default");
  });

  it("scopes plugin renderers to their owner plugin", () => {
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "test_tool",
      target: "result",
      priority: 100,
      decide: () => ({ action: "hide" }),
    });

    const decision = toolRendererRegistry.resolve(
      makeContext({ sourcePluginId: "plugin_b" }),
      "result"
    );
    expect(decision.action).toBe("default");
  });

  it("respects priority order (lower runs first)", () => {
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "test_tool",
      target: "result",
      priority: 50,
      decide: () => ({
        action: "render",
        node: createElement("div", null, "first"),
      }),
    });
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "test_tool",
      target: "result",
      priority: 200,
      decide: () => ({
        action: "render",
        node: createElement("div", null, "second"),
      }),
    });

    const renderers = toolRendererRegistry.getRenderers().filter(
      (renderer) => renderer.ownerPluginId === "plugin_a"
    );
    expect(renderers[0].priority).toBe(50);
    expect(renderers[1].priority).toBe(200);
  });

  it("removes renderers on unregisterPlugin", () => {
    toolRendererRegistry.registerPluginRenderer("plugin_a", {
      toolName: "test_tool",
      target: "result",
      priority: 100,
      decide: () => ({ action: "hide" }),
    });
    toolRendererRegistry.unregisterPlugin("plugin_a");

    const decision = toolRendererRegistry.resolve(
      makeContext({ sourcePluginId: "plugin_a" }),
      "result"
    );
    expect(decision.action).toBe("default");
  });
});
