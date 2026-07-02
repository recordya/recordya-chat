import { createElement, type ReactNode } from "react";
import type { ResultRenderContext } from "./ResultRegistry";
import { ChoicesWidget } from "./widgets/ChoicesWidget";

type WidgetRendererAction = "default" | "hide" | "render";
export type WidgetVisibility = "core" | "private" | "public";

export interface WidgetRenderDecision {
  action: WidgetRendererAction;
  node?: ReactNode;
}

export interface WidgetRenderer {
  widgetType: string;
  priority: number;
  decide: (context: ResultRenderContext, payload: Record<string, unknown>) => WidgetRenderDecision;
  condition?: (context: ResultRenderContext, payload: Record<string, unknown>) => boolean;
  ownerPluginId?: string;
  visibility?: WidgetVisibility;
}

export interface WidgetDescriptor {
  widgetType: string;
  payload: Record<string, unknown>;
}

class WidgetRegistry {
  private renderers: WidgetRenderer[] = [];
  private publicWidgetsByPlugin: Map<string, Set<string>> = new Map();

  registerRenderer(config: WidgetRenderer): void {
    this.renderers.push(config);
    this.renderers.sort((left, right) => left.priority - right.priority);
  }

  registerCoreRenderer(config: Omit<WidgetRenderer, "visibility" | "ownerPluginId">): void {
    this.registerRenderer({
      ...config,
      visibility: "core",
    });
  }

  registerPluginRenderer(
    pluginId: string,
    config: Omit<WidgetRenderer, "visibility" | "ownerPluginId">
  ): void {
    this.registerRenderer({
      ...config,
      ownerPluginId: pluginId,
      visibility: "private",
    });
  }

  unregisterPlugin(pluginId: string): void {
    this.renderers = this.renderers.filter((renderer) => renderer.ownerPluginId !== pluginId);
    this.publicWidgetsByPlugin.delete(pluginId);
  }

  setPluginPublicWidgets(pluginId: string, widgetTypes: string[]): void {
    const normalized = widgetTypes
      .map((widgetType) => String(widgetType).trim())
      .filter((widgetType) => widgetType.length > 0);
    this.publicWidgetsByPlugin.set(pluginId, new Set(normalized));
  }

  private isRendererVisible(renderer: WidgetRenderer, context: ResultRenderContext): boolean {
    if (renderer.visibility === "core" || !renderer.ownerPluginId) {
      return true;
    }
    const contextPluginId = context.sourcePluginId ?? context.agentId;
    if (contextPluginId === renderer.ownerPluginId) {
      return true;
    }
    const publicWidgets = this.publicWidgetsByPlugin.get(renderer.ownerPluginId);
    if (!publicWidgets) {
      return false;
    }
    return publicWidgets.has(renderer.widgetType);
  }

  resolve(context: ResultRenderContext, descriptor: WidgetDescriptor): WidgetRenderDecision {
    for (const renderer of this.renderers) {
      if (renderer.widgetType !== descriptor.widgetType) {
        continue;
      }
      try {
        if (!this.isRendererVisible(renderer, context)) {
          continue;
        }
        if (renderer.condition && !renderer.condition(context, descriptor.payload)) {
          continue;
        }
        const decision = renderer.decide(context, descriptor.payload);
        if (decision.action === "default" || decision.action === "hide") {
          return decision;
        }
        if (decision.action === "render" && decision.node) {
          return decision;
        }
      } catch (error) {
        console.warn(`Widget renderer '${descriptor.widgetType}' failed:`, error);
      }
    }
    return { action: "default" };
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function extractWidgetDescriptor(
  rows: Record<string, unknown>[]
): WidgetDescriptor | null {
  for (const row of rows) {
    const widgetType = String(row._widget_type ?? "").trim();
    if (!widgetType) {
      continue;
    }
    const payload = asRecord(row._widget_payload) ?? row;
    return { widgetType, payload };
  }
  return null;
}

export const widgetRegistry = new WidgetRegistry();

widgetRegistry.registerCoreRenderer({
  widgetType: "make_choices",
  priority: 100,
  decide: (context, payload) => ({
    action: "render",
    node: createElement(ChoicesWidget, {
      context,
      payload,
    }),
  }),
});
