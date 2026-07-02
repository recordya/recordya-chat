import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import recordyaLogo from "@/assets/recordya-logo.png";
import { getShowBranding, getAuthConfig } from "@/lib/config";
import { consumeCrossTabLogoutFlag } from "@/lib/auth-session";

export default function Auth() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Read the cross-tab logout flag once at mount. If set, we suppress
  // the auto-SSO redirect and show a manual relogin screen so the
  // user controls when this tab re-enters the Keycloak flow.
  const [crossTabLogout, setCrossTabLogout] = useState<boolean>(() =>
    consumeCrossTabLogoutFlag(),
  );

  const { signIn } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const isKeycloak = getAuthConfig().authMode === "keycloak";

  // Auto-redirect to Keycloak in SSO mode — unless this tab was just
  // logged out by a sibling tab (then the user must click manually).
  useEffect(() => {
    if (isKeycloak && !crossTabLogout) {
      signIn("", "");
    }
  }, [isKeycloak, crossTabLogout, signIn]);

  const handleManualRelogin = () => {
    // Clear the flag — the auto-SSO effect above will then fire.
    setCrossTabLogout(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      const { error } = await signIn(email, password);
      if (error) {
        toast.error(error.message);
      } else {
        toast.success(t("auth:loginSuccess"));
        navigate("/");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // Cross-tab logout: dedicated screen with a manual relogin button.
  if (isKeycloak && crossTabLogout) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl">{t("auth:crossTabTitle")}</CardTitle>
            <CardDescription>
              {t("auth:crossTabDescription")}
            </CardDescription>
          </CardHeader>
          <CardFooter>
            <Button type="button" className="w-full" onClick={handleManualRelogin}>
              {t("auth:reloginButton")}
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  // In Keycloak mode, show a loading spinner while redirecting
  if (isKeycloak) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-background p-4">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="mt-4 text-muted-foreground">{t("auth:redirecting")}</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{t("auth:title")}</CardTitle>
          <CardDescription>
            {t("auth:description")}
          </CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">{t("common:email")}</Label>
              <Input
                id="email"
                type="email"
                placeholder={t("auth:emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">{t("auth:password")}</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>
          </CardContent>
          <CardFooter>
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {t("auth:title")}
            </Button>
          </CardFooter>
        </form>
      </Card>

      {getShowBranding() && (
        <div className="flex items-center justify-center gap-1.5 mt-6">
          <span className="text-xs text-muted-foreground/60">{t("common:poweredBy")}</span>
          <a
            href="https://recordya.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:opacity-80 transition-opacity"
          >
            <img src={recordyaLogo} alt="Recordya" className="h-6" />
          </a>
        </div>
      )}
    </div>
  );
}
