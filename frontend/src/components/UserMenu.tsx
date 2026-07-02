import { useState } from "react";
import { LogOut, Settings } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { SettingsDialog } from "./SettingsDialog";

interface UserMenuProps {
  collapsed?: boolean;
}

export function UserMenu({ collapsed = false }: UserMenuProps) {
  const { user, signOut, getDisplayName } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const displayName = getDisplayName() || t("common:userFallback");
  const initials = displayName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  const email = user?.email || "";

  const handleSignOut = async () => {
    const { error } = await signOut();
    if (error) {
      toast.error(t("common:signOutError"));
    } else {
      toast.success(t("common:signOutSuccess"));
      navigate("/auth");
    }
  };

  if (!user) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            className={collapsed 
              ? "flex items-center justify-center p-1 rounded-md hover:bg-sidebar-accent transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring"
              : "flex items-center gap-3 w-full p-2 rounded-md hover:bg-sidebar-accent transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring"
            }
            aria-label={t("common:userMenu")}
          >
            <Avatar className="h-7 w-7 shrink-0">
              <AvatarFallback className="bg-muted-foreground/20 text-muted-foreground text-xs font-medium">
                {initials}
              </AvatarFallback>
            </Avatar>
            {!collapsed && (
              <span className="text-sm font-medium truncate flex-1 text-left">
                {displayName}
              </span>
            )}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          side={collapsed ? "right" : "top"}
          align={collapsed ? "start" : "start"}
          className="w-64 p-2"
        >
          {/* User header */}
          <div className="flex items-center gap-3 px-2 py-3">
            <Avatar className="h-7 w-7 shrink-0">
              <AvatarFallback className="bg-muted-foreground/20 text-muted-foreground text-xs font-medium">
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="flex flex-col min-w-0">
              <span className="text-sm font-semibold truncate">{displayName}</span>
              <span className="text-xs text-muted-foreground truncate">@{email.split("@")[0]}</span>
            </div>
          </div>
          
          <DropdownMenuSeparator className="mx-2" />
          
          <DropdownMenuItem onClick={() => setSettingsOpen(true)} className="cursor-pointer gap-3 py-2.5">
            <Settings className="h-4 w-4" />
            {t("common:settings")}
          </DropdownMenuItem>
          
          <DropdownMenuSeparator className="mx-2" />
          
          <DropdownMenuItem
            onClick={handleSignOut}
            className="cursor-pointer gap-3 py-2.5 text-red-600 focus:text-red-600 focus:bg-red-50 dark:focus:bg-red-950/40"
          >
            <LogOut className="h-4 w-4" />
            {t("common:signOut")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </>
  );
}
