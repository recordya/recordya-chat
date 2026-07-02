import type { ReactNode } from "react";

export type PluginEventType =
  | "message.render"
  | "welcome.render"
  | "status.update";

export interface PluginEvent<T = unknown> {
  type: PluginEventType;
  pluginId: string;
  data: T;
}

export interface WelcomeEventData {
  title?: string;
  description?: string;
  suggestions?: Array<{
    text: string;
    icon?: string;
  }>;
}

export interface StatusEventData {
  message: string;
  step?: number;
}

type EventHandler<T = unknown> = (event: PluginEvent<T>) => ReactNode | null;

class PluginEventBus {
  private handlers = new Map<string, Map<PluginEventType, EventHandler>>();
  private listeners = new Map<string, Set<() => void>>();

  register<T = unknown>(
    pluginId: string,
    eventType: PluginEventType,
    handler: EventHandler<T>
  ): void {
    if (!this.handlers.has(pluginId)) {
      this.handlers.set(pluginId, new Map());
    }
    this.handlers.get(pluginId)!.set(eventType, handler as EventHandler);
    this.notifyListeners(pluginId);
  }

  unregister(pluginId: string, eventType: PluginEventType): void {
    const pluginHandlers = this.handlers.get(pluginId);
    if (pluginHandlers) {
      pluginHandlers.delete(eventType);
      if (pluginHandlers.size === 0) {
        this.handlers.delete(pluginId);
      }
      this.notifyListeners(pluginId);
    }
  }

  dispatch<T = unknown>(event: PluginEvent<T>): ReactNode | null {
    const pluginHandlers = this.handlers.get(event.pluginId);
    if (!pluginHandlers) return null;

    const handler = pluginHandlers.get(event.type);
    if (!handler) return null;

    return handler(event as PluginEvent);
  }

  hasHandler(pluginId: string, eventType: PluginEventType): boolean {
    return this.handlers.get(pluginId)?.has(eventType) ?? false;
  }

  getRegisteredPlugins(): string[] {
    return Array.from(this.handlers.keys());
  }

  subscribe(pluginId: string, callback: () => void): () => void {
    if (!this.listeners.has(pluginId)) {
      this.listeners.set(pluginId, new Set());
    }
    this.listeners.get(pluginId)!.add(callback);

    return () => {
      const pluginListeners = this.listeners.get(pluginId);
      if (pluginListeners) {
        pluginListeners.delete(callback);
        if (pluginListeners.size === 0) {
          this.listeners.delete(pluginId);
        }
      }
    };
  }

  private notifyListeners(pluginId: string): void {
    const pluginListeners = this.listeners.get(pluginId);
    if (pluginListeners) {
      pluginListeners.forEach((callback) => callback());
    }
  }
}

export const pluginEventBus = new PluginEventBus();
