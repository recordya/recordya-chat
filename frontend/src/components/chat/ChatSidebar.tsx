import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, MoreHorizontal, Pencil, Search, SquarePen, Trash2, X, Mic, BarChart3, Database } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  useSidebar,
} from "@/components/ui/sidebar";

import type { Chat } from "@/hooks/use-chat-history";
import type { DataSourceInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

// Map of Lucide icon names to components
const iconMap: Record<string, React.ElementType> = {
  mic: Mic,
  "bar-chart-3": BarChart3,
  database: Database,
};

interface ChatRowProps {
  chat: Chat;
  active: boolean;
  collapsed: boolean;
  isEditing: boolean;
  editingTitle: string;
  onEditingTitleChange: (value: string) => void;
  onSelect: () => void;
  onStartEditing: () => void;
  onSaveEdit: () => void;
  onCancelEdit: () => void;
  onDelete: () => void;
}

function ChatRow({
  chat,
  active,
  collapsed,
  isEditing,
  editingTitle,
  onEditingTitleChange,
  onSelect,
  onStartEditing,
  onSaveEdit,
  onCancelEdit,
  onDelete,
}: ChatRowProps) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);

  if (isEditing && !collapsed) {
    return (
      <div className="flex items-center gap-1 px-2 py-1 rounded-md bg-muted">
        <input
          type="text"
          value={editingTitle}
          onChange={(e) => onEditingTitleChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSaveEdit();
            if (e.key === "Escape") onCancelEdit();
          }}
          onBlur={onSaveEdit}
          className="flex-1 min-w-0 h-7 px-2 text-sm bg-background border border-border rounded outline-none focus:ring-1 focus:ring-ring"
          autoFocus
        />

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onMouseDown={(e) => e.preventDefault()}
          onClick={onSaveEdit}
          aria-label={t("chat:saveName")}
        >
          <Check className="h-4 w-4" />
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onMouseDown={(e) => e.preventDefault()}
          onClick={onCancelEdit}
          aria-label={t("common:cancel")}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group/row relative flex items-center w-full mx-0.5 rounded-md transition-colors cursor-pointer",
        active || menuOpen
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
      )}
      onClick={onSelect}
    >
      <span
        className={cn(
          "flex-1 min-w-0 h-8 px-2.5 flex items-center text-sm truncate transition-all",
          (menuOpen || active) ? "mr-7" : "group-hover/row:mr-7",
          active && "font-medium"
        )}
      >
        {chat.title}
      </span>

      {!collapsed && (
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className={cn(
                "absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-sidebar-foreground transition-opacity",
                menuOpen ? "opacity-100" : "opacity-0 group-hover/row:opacity-100"
              )}
              aria-label={t("chat:chatMenu")}
              title={t("chat:menu")}
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="right" className="w-40">
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation();
                onStartEditing();
              }}
              className="cursor-pointer"
            >
              <Pencil className="mr-2 h-4 w-4" />
              {t("chat:rename")}
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="cursor-pointer text-destructive focus:text-destructive"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              {t("chat:delete")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

interface ChatSidebarProps {
  chats: Chat[];
  currentChatId: string | null;
  agents: DataSourceInfo[];
  agentsLoaded: boolean;
  selectedAgent: string | null;
  onSelectChat: (chatId: string) => void;
  onNewChat: () => void;
  onDeleteChat: (chatId: string) => void;
  onRenameChat: (chatId: string, newTitle: string) => void;
  onSearch: (query: string) => void;
  onSelectAgent: (agentId: string) => void;
}

export function ChatSidebar({
  chats,
  currentChatId,
  agents,
  agentsLoaded,
  selectedAgent,
  onSelectChat,
  onNewChat,
  onDeleteChat,
  onRenameChat,
  onSearch,
  onSelectAgent,
}: ChatSidebarProps) {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [editingChatId, setEditingChatId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const { state } = useSidebar();
  const collapsed = state === "collapsed";

  const debounceRef = useRef<number | null>(null);

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);

    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }

    debounceRef.current = window.setTimeout(() => {
      onSearch(value);
    }, 350);
  };

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const startEditing = (chat: Chat) => {
    setEditingChatId(chat.id);
    setEditingTitle(chat.title);
  };

  const saveEdit = () => {
    const next = editingTitle.trim();
    if (editingChatId && next) {
      onRenameChat(editingChatId, next);
    }
    setEditingChatId(null);
    setEditingTitle("");
  };

  const cancelEdit = () => {
    setEditingChatId(null);
    setEditingTitle("");
  };

  return (
    <Sidebar collapsible="offcanvas" className="border-r border-border bg-sidebar">
      <SidebarHeader className="p-2">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={onNewChat} className="h-9 px-2 gap-2">
              <SquarePen className="h-4 w-4" />
              {!collapsed && <span className="text-sm">{t("chat:newChat")}</span>}
            </SidebarMenuButton>
          </SidebarMenuItem>

          {!collapsed && (
            <SidebarMenuItem>
              {showSearch ? (
                <div className="flex items-center h-9 px-2">
                  <Search className="h-4 w-4 mr-2 flex-shrink-0 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder={t("chat:searchChats")}
                    value={searchQuery}
                    onChange={(e) => handleSearchChange(e.target.value)}
                    onBlur={() => {
                      if (!searchQuery) setShowSearch(false);
                    }}
                    className="flex-1 min-w-0 h-7 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                    autoFocus
                  />
                </div>
              ) : (
                <SidebarMenuButton onClick={() => setShowSearch(true)} className="h-9 px-2 gap-2">
                  <Search className="h-4 w-4" />
                  <span className="text-sm">{t("chat:search")}</span>
                </SidebarMenuButton>
              )}
            </SidebarMenuItem>
          )}
        </SidebarMenu>
      </SidebarHeader>

      {!collapsed ? (
        <SidebarContent>
          {/* Agents section */}
          <SidebarGroup>
            <SidebarGroupLabel className="px-2 text-xs text-muted-foreground font-normal">
              {t("chat:agents")}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="px-1 gap-0.5">
                {agents.length === 0 && (
                  <div className="px-2 py-2 text-xs text-muted-foreground">
                    {agentsLoaded ? t("chat:noAgents") : t("common:loading")}
                  </div>
                )}
                {agents.map((agent) => {
                  const IconComponent = iconMap[agent.agent?.icon || ""] || Database;
                  const isSelected = selectedAgent === agent.name;
                  return (
                    <SidebarMenuItem key={agent.name} className="mx-1">
                        <SidebarMenuButton
                          onClick={() => onSelectAgent(agent.name)}
                          className={cn(
                            "h-auto py-2 px-2.5 gap-2",
                            isSelected && "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                          )}
                        >
                          <IconComponent className="h-5 w-5 text-muted-foreground flex-shrink-0" />
                          <div className="flex flex-col min-w-0">
                            <span className="truncate text-sm">{agent.display_name}</span>
                            <span className="truncate text-xs text-muted-foreground font-normal">
                              {agent.description}
                            </span>
                          </div>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>

          {/* Chats section */}
          <SidebarGroup className="flex-1 min-h-0">
            <SidebarGroupLabel className="px-2 text-xs text-muted-foreground font-normal">
              {t("chat:yourChats")}
            </SidebarGroupLabel>

            <SidebarGroupContent className="flex-1 min-h-0 overflow-hidden">
              <div className="h-full overflow-y-auto">
                <SidebarMenu className="px-1 gap-0.5">
                  {chats.map((chat) => (
                    <SidebarMenuItem key={chat.id} className="mx-1">
                      <ChatRow
                        chat={chat}
                        active={currentChatId === chat.id}
                        collapsed={collapsed}
                        isEditing={editingChatId === chat.id}
                        editingTitle={editingTitle}
                        onEditingTitleChange={setEditingTitle}
                        onSelect={() => onSelectChat(chat.id)}
                        onStartEditing={() => startEditing(chat)}
                        onSaveEdit={saveEdit}
                        onCancelEdit={cancelEdit}
                        onDelete={() => onDeleteChat(chat.id)}
                      />
                    </SidebarMenuItem>
                  ))}

                  {chats.length === 0 && (
                    <div className="px-2 py-6 text-center text-sm text-muted-foreground">{t("chat:noChats")}</div>
                  )}
                </SidebarMenu>
              </div>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      ) : (
        <div className="flex-1" />
      )}

    </Sidebar>
  );
}
