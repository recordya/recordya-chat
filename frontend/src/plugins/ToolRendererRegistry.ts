import type { ReactNode } from "react";

export type ToolRenderTarget = "arguments" | "result";
export type ToolRenderAction = "default" | "hide" | "render";

export interface ToolRenderContext {
  toolId: string;
  toolName: string;
  agentId?: string;
  sourcePluginId?: string;
  status: "running" | "done" | "error";
  arguments: Record<string, unknown>;
  result?: Record<string, unknown>;
  durationMs?: number;
  rowCount?: number | null;
  error?: string | null;
}

export interface ToolRenderDecision {
  action: ToolRenderAction;
  node?: ReactNode;
}

export interface ToolRenderer {
  toolName: string;
  target: ToolRenderTarget;
  priority: number;
  decide: (context: ToolRenderContext) => ToolRenderDecision;
  condition?: (context: ToolRenderContext) => boolean;
  ownerPluginId?: string;
}

class ToolRendererRegistry {
  private renderers: ToolRenderer[] = [];

  registerRenderer(config: ToolRenderer): void {
    this.renderers.push(config);
    this.renderers.sort((left, right) => left.priority - right.priority);
  }

  registerPluginRenderer(
    pluginId: string,
    config: Omit<ToolRenderer, "ownerPluginId">
  ): void {
    this.registerRenderer({ ...config, ownerPluginId: pluginId });
  }

  unregisterPlugin(pluginId: string): void {
    this.renderers = this.renderers.filter(
      (renderer) => renderer.ownerPluginId !== pluginId
    );
  }

  private isRendererVisible(
    renderer: ToolRenderer,
    context: ToolRenderContext
  ): boolean {
    if (!renderer.ownerPluginId) {
      return true;
    }
    const contextPluginId = context.sourcePluginId ?? context.agentId;
    if (!contextPluginId) {
      return true;
    }
    return contextPluginId === renderer.ownerPluginId;
  }

  resolve(
    context: ToolRenderContext,
    target: ToolRenderTarget
  ): ToolRenderDecision {
    for (const renderer of this.renderers) {
      if (renderer.toolName !== context.toolName || renderer.target !== target) {
        continue;
      }
      try {
        if (!this.isRendererVisible(renderer, context)) {
          continue;
        }
        if (renderer.condition && !renderer.condition(context)) {
          continue;
        }
        const decision = renderer.decide(context);
        if (decision.action === "default" || decision.action === "hide") {
          return decision;
        }
        if (decision.action === "render" && decision.node) {
          return decision;
        }
      } catch (error) {
        console.warn(
          `Tool renderer '${renderer.toolName}/${renderer.target}' failed:`,
          error
        );
      }
    }
    return { action: "default" };
  }

  getRenderers(): ToolRenderer[] {
    return [...this.renderers];
  }
}

export const toolRendererRegistry = new ToolRendererRegistry();
