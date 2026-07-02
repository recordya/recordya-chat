import type { ComponentType } from "react";

export type SlotName =
  | "sidebar.agents.before"
  | "sidebar.agents.after"
  | "sidebar.navigation"
  | "chat.welcome"
  | "chat.input.before"
  | "chat.input.after"
  | "chat.message.actions"
  | "chat.message.content"
  | "detail.panel"
  | "layout.header"
  | "layout.footer"
  | "settings.users.row.header"
  | "settings.users.row.extra"
  | "settings.users.add.fields";

export interface SlotContext {
  agentId?: string;
  messageId?: string;
  [key: string]: unknown;
}

interface SlotComponent {
  pluginId: string;
  component: ComponentType<SlotContext>;
  order: number;
  condition?: (context: SlotContext) => boolean;
}

export interface SlotRegistration {
  pluginId: string;
  component: ComponentType<SlotContext>;
  order?: number;
  condition?: (context: SlotContext) => boolean;
}

class SlotRegistry {
  private slots = new Map<SlotName, SlotComponent[]>();

  register(slot: SlotName, config: SlotRegistration): void {
    const entry: SlotComponent = {
      pluginId: config.pluginId,
      component: config.component,
      order: config.order ?? 100,
      condition: config.condition,
    };

    const existing = this.slots.get(slot) || [];
    existing.push(entry);
    existing.sort((a, b) => a.order - b.order);
    this.slots.set(slot, existing);
  }

  unregister(slot: SlotName, pluginId: string): void {
    const existing = this.slots.get(slot);
    if (existing) {
      const filtered = existing.filter((c) => c.pluginId !== pluginId);
      if (filtered.length > 0) {
        this.slots.set(slot, filtered);
      } else {
        this.slots.delete(slot);
      }
    }
  }

  getComponents(
    slot: SlotName,
    context: SlotContext
  ): ComponentType<SlotContext>[] {
    return (this.slots.get(slot) || [])
      .filter((c) => !c.condition || c.condition(context))
      .map((c) => c.component);
  }

  hasComponents(slot: SlotName): boolean {
    return (this.slots.get(slot)?.length ?? 0) > 0;
  }

  getRegisteredSlots(): SlotName[] {
    return Array.from(this.slots.keys());
  }
}

export const slotRegistry = new SlotRegistry();
