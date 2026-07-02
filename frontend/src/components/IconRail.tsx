import { Bot, LayoutGrid, icons, type LucideIcon } from "lucide-react";
import { UserMenu } from "@/components/UserMenu";
import { cn } from "@/lib/utils";
import type { NavItem } from "@/plugins/ViewRegistry";

/**
 * Resolve a kebab-case Lucide icon name (e.g. "clipboard-list") to a
 * LucideIcon component.  Falls back to LayoutGrid if the name is unknown.
 *
 * Uses the `icons` object exported by lucide-react which maps PascalCase
 * names to components — no hardcoded map needed.
 */
/** @internal — exported for testing */
export function resolveLucideIcon(name: string | undefined): LucideIcon {
  if (!name) return LayoutGrid;

  // Convert kebab-case to PascalCase: "clipboard-list" → "ClipboardList"
  const pascalCase = name
    .split("-")
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join("");

  return (icons as Record<string, LucideIcon>)[pascalCase] ?? LayoutGrid;
}

/** Core "AI" rail item — always present, order 0. */
const CHAT_ITEM = {
  id: "__core_chat__",
  label: "AI",
  icon: Bot,
  order: 0,
} as const;

interface RailItem {
  id: string;
  label: string;
  icon: LucideIcon;
  order: number;
}

interface IconRailProps {
  /** Currently active rail item id */
  activeId: string;
  /** Plugin nav items from ViewRegistry.getNavItems() */
  pluginNavItems: NavItem[];
  /** Called when user clicks a rail icon */
  onSelect: (id: string) => void;
}

export const CHAT_VIEW_ID = CHAT_ITEM.id;

export function IconRail({ activeId, pluginNavItems, onSelect }: IconRailProps) {
  // Build the full list: core chat + plugin items
  const items: RailItem[] = [
    { ...CHAT_ITEM, icon: CHAT_ITEM.icon },
    ...pluginNavItems.map((nav) => ({
      id: nav.id,
      label: nav.label,
      icon: resolveLucideIcon(nav.icon),
      order: nav.order,
    })),
  ].sort((a, b) => a.order - b.order);

  return (
    <div className="flex flex-col h-svh w-20 shrink-0 border-r border-border bg-sidebar z-50">
      {/* Rail icons */}
      <nav className="flex flex-col items-center gap-1 pt-2 px-1.5 flex-1">
        {items.map((item) => {
          const Icon = item.icon;
          const isActive = activeId === item.id;

          return (
            <button
              key={item.id}
              onClick={() => onSelect(item.id)}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 w-full py-1.5 rounded-lg transition-colors",
                isActive
                  ? "bg-sidebar-accent-foreground/10 text-sidebar-accent-foreground"
                  : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              )}
              aria-label={item.label}
            >
              <Icon className="h-5 w-5" />
              <span className="text-[10px] leading-tight max-w-full px-1 break-words line-clamp-2 text-center">
                {item.label}
              </span>
            </button>
          );
        })}
      </nav>

      {/* User menu at bottom */}
      <div className="flex flex-col items-center pb-3 px-1.5">
        <UserMenu collapsed />
      </div>
    </div>
  );
}
