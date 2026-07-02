import { useEffect, useMemo, useState } from "react";
import { Cpu, Plus, Search, User as UserIcon, Users } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Slot } from "@/components/Slot";
import { cn } from "@/lib/utils";
import { VisuallyHidden } from "@radix-ui/react-visually-hidden";
import { useModelSettings } from "@/contexts/ModelSettingsContext";
import { useAuth } from "@/hooks/useAuth";
import {
  activateUser,
  createUser,
  deactivateUser,
  listUsers,
  updateProfile,
  type UserResponse,
} from "@/lib/api";
import { toast } from "sonner";
import { Trans, useTranslation } from "react-i18next";

interface SettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type SettingsTab = "profile" | "users" | "models";

const ALL_SIDEBAR_ITEMS = [
  { id: "profile" as const, labelKey: "settings:profile", icon: UserIcon },
  { id: "users" as const, labelKey: "settings:users", icon: Users },
  { id: "models" as const, labelKey: "settings:models", icon: Cpu },
];

export function SettingsDialog({ open, onOpenChange }: SettingsDialogProps) {
  const { user } = useAuth();
  const { t } = useTranslation();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const sidebarItems = useMemo(
    () => (isAdmin ? ALL_SIDEBAR_ITEMS : ALL_SIDEBAR_ITEMS.filter((item) => item.id === "profile")),
    [isAdmin],
  );
  const [activeTab, setActiveTab] = useState<SettingsTab>("profile");

  useEffect(() => {
    if (!isAdmin && activeTab !== "profile") {
      setActiveTab("profile");
    }
  }, [isAdmin, activeTab]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl p-0 gap-0 overflow-hidden">
        <VisuallyHidden>
          <DialogTitle>{t("common:settings")}</DialogTitle>
        </VisuallyHidden>
        <div className="flex h-[640px]">
          {/* Sidebar */}
          <div className="w-52 border-r bg-muted/30 p-3 flex flex-col">
            <nav className="space-y-1">
              {sidebarItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                    activeTab === item.id
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  {t(item.labelKey)}
                </button>
              ))}
            </nav>
          </div>

          {/* Content */}
          <div className="flex-1 p-6 overflow-y-auto">
            {activeTab === "profile" && <ProfileSettings />}
            {isAdmin && activeTab === "users" && <UsersSettings open={open} />}
            {isAdmin && activeTab === "models" && <ModelsSettings />}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ProfileSettings() {
  const { user, refreshUser } = useAuth();
  const { t } = useTranslation();
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDisplayName(user?.display_name ?? "");
  }, [user?.display_name]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateProfile({ display_name: displayName });
      await refreshUser();
      toast.success(t("settings:saveSuccess"));
    } catch {
      toast.error(t("settings:saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h2 className="text-xl font-semibold mb-6">{t("settings:profile")}</h2>
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="profile-email">{t("common:email")}</Label>
          <Input
            id="profile-email"
            type="email"
            value={user?.email ?? ""}
            disabled
            readOnly
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="profile-name">{t("settings:fullName")}</Label>
          <Input
            id="profile-name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>
        <div className="flex justify-end pt-2">
          <Button onClick={handleSave} disabled={saving}>
            {t("settings:saveChanges")}
          </Button>
        </div>
      </div>
    </div>
  );
}

type UserStatusFilter = "active" | "inactive" | "all";

function UsersSettings({ open }: { open: boolean }) {
  const { user: currentUser } = useAuth();
  const { t } = useTranslation();
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<UserStatusFilter>("active");
  const [pendingDeactivate, setPendingDeactivate] = useState<UserResponse | null>(null);
  const [deactivating, setDeactivating] = useState(false);
  const [activatingId, setActivatingId] = useState<string | null>(null);

  const reload = async () => {
    setLoading(true);
    setError(null);
    try {
      const items = await listUsers();
      setUsers(items);
    } catch {
      setError(t("settings:loadUsersError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void reload();
  }, [open]);

  const visibleUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    return users.filter((u) => {
      if (u.role === "admin" || u.role === "super_admin") return false;
      const enabled = u.enabled !== false;
      if (statusFilter === "active" && !enabled) return false;
      if (statusFilter === "inactive" && enabled) return false;
      if (!q) return true;
      const haystack = `${u.display_name ?? ""} ${u.email}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [users, search, statusFilter]);

  const handleDeactivate = async () => {
    if (!pendingDeactivate) return;
    setDeactivating(true);
    try {
      await deactivateUser(pendingDeactivate.user_id);
      toast.success(t("settings:deactivateSuccess"));
      setPendingDeactivate(null);
      await reload();
    } catch {
      toast.error(t("settings:deactivateError"));
    } finally {
      setDeactivating(false);
    }
  };

  const handleActivate = async (user: UserResponse) => {
    setActivatingId(user.user_id);
    try {
      await activateUser(user.user_id);
      toast.success(t("settings:activateSuccess"));
      await reload();
    } catch (err) {
      const message = err instanceof Error ? err.message : t("settings:activateError");
      toast.error(message);
    } finally {
      setActivatingId(null);
    }
  };

  return (
    <div>
      <h2 className="text-xl font-semibold mb-6">{t("settings:users")}</h2>

      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder={t("settings:searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as UserStatusFilter)}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">{t("settings:statusActive")}</SelectItem>
            <SelectItem value="inactive">{t("settings:statusInactive")}</SelectItem>
            <SelectItem value="all">{t("settings:statusAll")}</SelectItem>
          </SelectContent>
        </Select>
        <AddUserPopover onCreated={reload} />
      </div>

      <div className="rounded-md border">
        <div className="grid grid-cols-[1fr_auto_140px] gap-4 items-center px-4 py-2.5 text-xs font-medium text-muted-foreground border-b">
          <span>{t("settings:userColumn")}</span>
          <span>
            <Slot name="settings.users.row.header" context={{}} />
          </span>
          <span className="text-right">{t("settings:statusColumn")}</span>
        </div>

        {loading && (
          <p className="px-4 py-6 text-sm text-muted-foreground">{t("common:loading")}</p>
        )}
        {!loading && error && (
          <p className="px-4 py-6 text-sm text-destructive">{error}</p>
        )}
        {!loading && !error && visibleUsers.length === 0 && (
          <p className="px-4 py-6 text-sm text-muted-foreground">{t("settings:noUsers")}</p>
        )}
        {!loading && !error && visibleUsers.map((u) => {
          const enabled = u.enabled !== false;
          const isSelf = currentUser?.user_id === u.user_id;
          return (
            <div
              key={u.user_id}
              className="grid grid-cols-[1fr_auto_140px] gap-4 items-center px-4 py-3 border-b last:border-b-0"
            >
              <div className="flex flex-col min-w-0">
                <span className="text-sm font-medium truncate">
                  {u.display_name || u.email.split("@")[0]}
                </span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="text-xs text-muted-foreground truncate">{u.email}</span>
                  </TooltipTrigger>
                  <TooltipContent>{u.email}</TooltipContent>
                </Tooltip>
              </div>
              <div className="flex items-center gap-2">
                <Slot name="settings.users.row.extra" context={{ user: u }} />
              </div>
              <div className="flex justify-end">
                {enabled ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={isSelf}
                    onClick={() => setPendingDeactivate(u)}
                  >
                    {t("settings:deactivate")}
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={activatingId === u.user_id}
                    onClick={() => handleActivate(u)}
                  >
                    {activatingId === u.user_id ? t("settings:activating") : t("settings:activate")}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <AlertDialog
        open={!!pendingDeactivate}
        onOpenChange={(o) => !o && !deactivating && setPendingDeactivate(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings:deactivateConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="settings:deactivateConfirmBody"
                values={{
                  name: pendingDeactivate?.display_name || pendingDeactivate?.email.split("@")[0],
                  email: pendingDeactivate?.email,
                }}
                components={{ bold: <span className="font-medium text-foreground" /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deactivating}>{t("common:cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeactivate} disabled={deactivating}>
              {deactivating ? t("settings:deactivating") : t("settings:deactivate")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function AddUserPopover({ onCreated }: { onCreated: () => Promise<void> | void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [pluginData, setPluginData] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setDisplayName("");
    setEmail("");
    setPluginData({});
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    try {
      await createUser({
        email: email.trim(),
        display_name: displayName.trim() || null,
        plugin_data: Object.keys(pluginData).length > 0 ? pluginData : undefined,
      });
      toast.success(t("settings:addUserSuccess"));
      reset();
      setOpen(false);
      await onCreated();
    } catch (err) {
      const message = err instanceof Error ? err.message : t("settings:addUserError");
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        if (!submitting) setOpen(o);
        if (!o) reset();
      }}
    >
      <PopoverTrigger asChild>
        <Button className="gap-2">
          <Plus className="h-4 w-4" />
          {t("settings:addUser")}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="new-user-name">{t("settings:fullName")}</Label>
            <Input
              id="new-user-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-user-email">{t("common:email")}</Label>
            <Input
              id="new-user-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <Slot
            name="settings.users.add.fields"
            context={{ pluginData, setPluginData }}
          />
          <Button type="submit" className="w-full" disabled={submitting || !email.trim()}>
            {submitting ? t("settings:adding") : t("settings:add")}
          </Button>
        </form>
      </PopoverContent>
    </Popover>
  );
}


function ModelsSettings() {
  const { availableModels, selectedModel, isLoading, setSelectedModel, refresh } =
    useModelSettings();
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleChange = async (model: string) => {
    setSaving(true);
    try {
      await setSelectedModel(model);
      toast.success(t("settings:saveSuccess"));
    } catch {
      toast.error(t("settings:saveError"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h2 className="text-xl font-semibold mb-6">{t("settings:models")}</h2>
      <div className="space-y-6">
        <div className="flex items-center justify-between py-3 border-b gap-4">
          <div className="flex-1">
            <span className="text-sm font-medium">{t("settings:modelAi")}</span>
            <p className="text-xs text-muted-foreground mt-1">
              {t("settings:modelDescription")}
            </p>
          </div>
          <Select
            value={selectedModel}
            onValueChange={handleChange}
            disabled={isLoading || saving || availableModels.length === 0}
          >
            <SelectTrigger className="w-48">
              <SelectValue placeholder={t("settings:selectModel")} />
            </SelectTrigger>
            <SelectContent>
              {availableModels.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  <div className="flex flex-col">
                    <span>{model.name}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}
