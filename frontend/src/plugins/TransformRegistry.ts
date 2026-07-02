import type { ReactNode } from "react";

export interface TextTransformer {
  pluginId: string;
  priority: number;
  transform: (text: string, context?: TransformContext) => string;
  condition?: (text: string, context?: TransformContext) => boolean;
}

export interface ContentRenderer {
  pluginId: string;
  priority: number;
  render: (text: string, context?: TransformContext) => ReactNode;
  condition?: (text: string, context?: TransformContext) => boolean;
}

export interface TransformContext {
  messageId?: string;
  agentId?: string;
  /** Plugin that produced the message (falls back to agentId). Lets a transform scope itself to its own plugin. */
  sourcePluginId?: string;
  /** Whether the message also carries rendered results (a widget or table shown separately). */
  hasResults?: boolean;
  isStreaming?: boolean;
  [key: string]: unknown;
}

class TransformRegistry {
  private transformers: TextTransformer[] = [];
  private renderers: ContentRenderer[] = [];

  registerTransformer(config: TextTransformer): void {
    this.transformers.push(config);
    this.transformers.sort((a, b) => a.priority - b.priority);
  }

  registerRenderer(config: ContentRenderer): void {
    this.renderers.push(config);
    this.renderers.sort((a, b) => a.priority - b.priority);
  }

  unregister(pluginId: string): void {
    this.transformers = this.transformers.filter((t) => t.pluginId !== pluginId);
    this.renderers = this.renderers.filter((r) => r.pluginId !== pluginId);
  }

  transform(text: string, context?: TransformContext): string {
    let result = text;

    for (const transformer of this.transformers) {
      try {
        if (!transformer.condition || transformer.condition(result, context)) {
          result = transformer.transform(result, context);
        }
      } catch (error) {
        console.warn(`Transformer ${transformer.pluginId} failed:`, error);
      }
    }

    return result;
  }

  render(text: string, context?: TransformContext): ReactNode {
    const transformed = this.transform(text, context);

    for (const renderer of this.renderers) {
      try {
        if (!renderer.condition || renderer.condition(transformed, context)) {
          return renderer.render(transformed, context);
        }
      } catch (error) {
        console.warn(`Renderer ${renderer.pluginId} failed:`, error);
      }
    }

    return transformed;
  }

  getTransformers(): TextTransformer[] {
    return [...this.transformers];
  }

  getRenderers(): ContentRenderer[] {
    return [...this.renderers];
  }
}

export const transformRegistry = new TransformRegistry();
