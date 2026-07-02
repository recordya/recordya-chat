import { describe, it, expect, beforeEach } from "vitest";
import { viewRegistry } from "./ViewRegistry";

function NoopView() {
  return null;
}

describe("ViewRegistry.getNavItems — roles propagation", () => {
  beforeEach(() => {
    viewRegistry.unregisterPlugin("test_both");
    viewRegistry.unregisterPlugin("test_user");
    viewRegistry.unregisterPlugin("test_default");
  });

  it("exposes roles array on nav item when registered with both roles", () => {
    viewRegistry.register({
      id: "test_both:/x",
      path: "/x",
      component: NoopView,
      pluginId: "test_both",
      showInNav: true,
      navLabel: "X",
      navOrder: 1,
      roles: ["admin", "user"],
    });

    const item = viewRegistry.getNavItems().find((n) => n.pluginId === "test_both");
    expect(item?.roles).toEqual(["admin", "user"]);
  });

  it("exposes roles array with single entry when registered for one role", () => {
    viewRegistry.register({
      id: "test_user:/y",
      path: "/y",
      component: NoopView,
      pluginId: "test_user",
      showInNav: true,
      navLabel: "Y",
      navOrder: 2,
      roles: ["user"],
    });

    const item = viewRegistry.getNavItems().find((n) => n.pluginId === "test_user");
    expect(item?.roles).toEqual(["user"]);
  });

  it("leaves roles undefined when omitted (admin-only by default)", () => {
    viewRegistry.register({
      id: "test_default:/z",
      path: "/z",
      component: NoopView,
      pluginId: "test_default",
      showInNav: true,
      navLabel: "Z",
      navOrder: 3,
    });

    const item = viewRegistry.getNavItems().find((n) => n.pluginId === "test_default");
    expect(item?.roles).toBeUndefined();
  });
});
