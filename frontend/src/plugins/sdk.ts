import type { ComponentType, ReactNode } from "react";
import { slotRegistry, type SlotName, type SlotContext } from "./SlotRegistry";
import { viewRegistry, type ViewProps, type Role } from "./ViewRegistry";
import { transformRegistry, type TransformContext } from "./TransformRegistry";
import {
  resultRegistry,
  type ResultRenderContext,
  type ResultRenderDecision,
} from "./ResultRegistry";
import { widgetRegistry, type WidgetRenderDecision } from "./WidgetRegistry";
import {
  toolRendererRegistry,
  type ToolRenderContext,
  type ToolRenderDecision,
  type ToolRenderTarget,
} from "./ToolRendererRegistry";
import { pluginEventBus, type PluginEventType, type PluginEvent } from "./EventBus";
import { formatConfigRegistry, type PluginFormatConfig } from "./FormatConfig";
import {
  referenceSuggestionRegistry,
  type ReferenceSuggestion,
} from "./ReferenceSuggestionRegistry";
import type { ComposerReference } from "@/utils/composerReferences";

export interface SlotOptions {
  order?: number;
  condition?: (context: SlotContext) => boolean;
}

export interface ViewOptions {
  showInNav?: boolean;
  navLabel?: string;
  navIcon?: string;
  navOrder?: number;
  permissions?: string[];
  roles?: Role[];
}

export interface TransformOptions {
  priority?: number;
  condition?: (text: string, context?: TransformContext) => boolean;
}

export interface ResultRenderOptions {
  priority?: number;
  condition?: (context: ResultRenderContext) => boolean;
}

export interface WidgetRenderOptions {
  priority?: number;
  condition?: (context: ResultRenderContext, payload: Record<string, unknown>) => boolean;
}

export interface ToolRendererOptions {
  toolName: string;
  target: ToolRenderTarget;
  decide: (context: ToolRenderContext) => ToolRenderDecision;
  priority?: number;
  condition?: (context: ToolRenderContext) => boolean;
}

export interface ReferenceSuggestionOptions {
  priority?: number;
}

export type EventHandler<T = unknown> = (event: PluginEvent<T>) => ReactNode | null;

export interface PluginSDK {
  readonly pluginId: string;
  slot(slot: SlotName, component: ComponentType<SlotContext>, options?: SlotOptions): void;
  view(path: string, component: ComponentType<ViewProps>, options?: ViewOptions): void;
  viewLazy(
    path: string,
    loader: () => Promise<{ default: ComponentType<ViewProps> }>,
    options?: ViewOptions
  ): void;
  transform(
    transform: (text: string, context?: TransformContext) => string,
    options?: TransformOptions
  ): void;
  renderer(
    render: (text: string, context?: TransformContext) => ReactNode,
    options?: TransformOptions
  ): void;
  results(
    decide: (context: ResultRenderContext) => ResultRenderDecision,
    options?: ResultRenderOptions
  ): void;
  widget(
    widgetType: string,
    decide: (context: ResultRenderContext, payload: Record<string, unknown>) => WidgetRenderDecision,
    options?: WidgetRenderOptions
  ): void;
  toolRenderer(options: ToolRendererOptions): void;
  referenceSuggestions(
    fetchSuggestions: (query: string, signal: AbortSignal) => Promise<ReferenceSuggestion[]>,
    options?: ReferenceSuggestionOptions
  ): void;
  conversationReferences(
    widgetType: string,
    extract: (payload: Record<string, unknown>) => ComposerReference[]
  ): void;
  on<T = unknown>(eventType: PluginEventType, handler: EventHandler<T>): void;
  emit<T = unknown>(eventType: PluginEventType, data: T): ReactNode | null;
  formatConfig(config: PluginFormatConfig): void;
  unregisterAll(): void;
}

export function createPluginSDK(pluginId: string): PluginSDK {
  const registeredSlots: SlotName[] = [];
  const registeredEvents: PluginEventType[] = [];

  return {
    pluginId,

    slot(slot: SlotName, component: ComponentType<SlotContext>, options?: SlotOptions): void {
      slotRegistry.register(slot, {
        pluginId,
        component,
        order: options?.order,
        condition: options?.condition,
      });
      registeredSlots.push(slot);
    },

    view(path: string, component: ComponentType<ViewProps>, options?: ViewOptions): void {
      const viewId = `${pluginId}:${path}`;
      viewRegistry.register({
        id: viewId,
        path,
        component,
        pluginId,
        showInNav: options?.showInNav,
        navLabel: options?.navLabel,
        navIcon: options?.navIcon,
        navOrder: options?.navOrder,
        permissions: options?.permissions,
        roles: options?.roles,
      });
    },

    viewLazy(
      path: string,
      loader: () => Promise<{ default: ComponentType<ViewProps> }>,
      options?: ViewOptions
    ): void {
      const viewId = `${pluginId}:${path}`;
      viewRegistry.registerLazy({
        id: viewId,
        path,
        loader,
        pluginId,
        showInNav: options?.showInNav,
        navLabel: options?.navLabel,
        navIcon: options?.navIcon,
        navOrder: options?.navOrder,
        permissions: options?.permissions,
        roles: options?.roles,
      });
    },

    transform(
      transform: (text: string, context?: TransformContext) => string,
      options?: TransformOptions
    ): void {
      transformRegistry.registerTransformer({
        pluginId,
        priority: options?.priority ?? 100,
        transform,
        condition: options?.condition,
      });
    },

    renderer(
      render: (text: string, context?: TransformContext) => ReactNode,
      options?: TransformOptions
    ): void {
      transformRegistry.registerRenderer({
        pluginId,
        priority: options?.priority ?? 100,
        render,
        condition: options?.condition,
      });
    },

    results(
      decide: (context: ResultRenderContext) => ResultRenderDecision,
      options?: ResultRenderOptions
    ): void {
      resultRegistry.registerRenderer({
        pluginId,
        priority: options?.priority ?? 100,
        decide,
        condition: options?.condition,
      });
    },

    widget(
      widgetType: string,
      decide: (context: ResultRenderContext, payload: Record<string, unknown>) => WidgetRenderDecision,
      options?: WidgetRenderOptions
    ): void {
      widgetRegistry.registerPluginRenderer(pluginId, {
        widgetType,
        priority: options?.priority ?? 100,
        decide,
        condition: options?.condition,
      });
    },

    toolRenderer(options: ToolRendererOptions): void {
      toolRendererRegistry.registerPluginRenderer(pluginId, {
        toolName: options.toolName,
        target: options.target,
        priority: options.priority ?? 100,
        decide: options.decide,
        condition: options.condition,
      });
    },

    referenceSuggestions(
      fetchSuggestions: (query: string, signal: AbortSignal) => Promise<ReferenceSuggestion[]>,
      options?: ReferenceSuggestionOptions
    ): void {
      referenceSuggestionRegistry.register({
        pluginId,
        priority: options?.priority ?? 100,
        fetchSuggestions,
      });
    },

    conversationReferences(
      widgetType: string,
      extract: (payload: Record<string, unknown>) => ComposerReference[]
    ): void {
      referenceSuggestionRegistry.registerExtractor({
        pluginId,
        widgetType,
        extract,
      });
    },

    on<T = unknown>(eventType: PluginEventType, handler: EventHandler<T>): void {
      pluginEventBus.register(pluginId, eventType, handler);
      registeredEvents.push(eventType);
    },

    emit<T = unknown>(eventType: PluginEventType, data: T): ReactNode | null {
      return pluginEventBus.dispatch({
        type: eventType,
        pluginId,
        data,
      });
    },

    formatConfig(config: PluginFormatConfig): void {
      formatConfigRegistry.register(pluginId, config);
    },

    unregisterAll(): void {
      for (const slot of registeredSlots) {
        slotRegistry.unregister(slot, pluginId);
      }
      registeredSlots.length = 0;

      viewRegistry.unregisterPlugin(pluginId);
      transformRegistry.unregister(pluginId);
      resultRegistry.unregister(pluginId);
      widgetRegistry.unregisterPlugin(pluginId);
      toolRendererRegistry.unregisterPlugin(pluginId);
      formatConfigRegistry.unregister(pluginId);
      referenceSuggestionRegistry.unregister(pluginId);

      for (const eventType of registeredEvents) {
        pluginEventBus.unregister(pluginId, eventType);
      }
      registeredEvents.length = 0;
    },
  };
}

export type { PluginEvent, PluginEventType } from "./EventBus";
export type { SlotName, SlotContext } from "./SlotRegistry";
export type { ViewProps, Role } from "./ViewRegistry";
export type { TransformContext } from "./TransformRegistry";
export type { ResultRenderContext, ResultRenderDecision } from "./ResultRegistry";
export type {
  ToolRenderContext,
  ToolRenderDecision,
  ToolRenderTarget,
  ToolRenderAction,
} from "./ToolRendererRegistry";
export type { WidgetRenderDecision } from "./WidgetRegistry";
export type { PluginFormatConfig, DurationLabels } from "./FormatConfig";
export type { ReferenceSuggestion } from "./ReferenceSuggestionRegistry";
export type { ComposerReference } from "@/utils/composerReferences";
export { DefaultResultsTableWidget } from "./widgets/DefaultResultsTableWidget";
