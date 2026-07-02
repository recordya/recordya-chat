import type { ReactNode } from "react";

export type ResultRendererAction = "default" | "hide" | "render";

export interface ResultRenderContext {
  agentId?: string;
  sourcePluginId?: string;
  messageId?: string;
  content: string;
  sql?: string;
  sqlMode?: "predefined" | "dynamic";
  queryResults: Record<string, unknown>[];
  fields: string[];
  durationFields: string[];
  submitUserMessage?: (text: string) => void;
  setComposerText?: (text: string) => void;
}

export interface ResultRenderDecision {
  action: ResultRendererAction;
  node?: ReactNode;
}

export interface ResultRenderer {
  pluginId: string;
  priority: number;
  decide: (context: ResultRenderContext) => ResultRenderDecision;
  condition?: (context: ResultRenderContext) => boolean;
}

class ResultRegistry {
  private renderers: ResultRenderer[] = [];

  registerRenderer(config: ResultRenderer): void {
    this.renderers.push(config);
    this.renderers.sort((left, right) => left.priority - right.priority);
  }

  unregister(pluginId: string): void {
    this.renderers = this.renderers.filter((renderer) => renderer.pluginId !== pluginId);
  }

  resolve(context: ResultRenderContext): ResultRenderDecision {
    for (const renderer of this.renderers) {
      try {
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
        console.warn(`Result renderer ${renderer.pluginId} failed:`, error);
      }
    }
    return { action: "default" };
  }

  getRenderers(): ResultRenderer[] {
    return [...this.renderers];
  }
}

export const resultRegistry = new ResultRegistry();
