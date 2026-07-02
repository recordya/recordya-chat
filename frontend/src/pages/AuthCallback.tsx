/**
 * OIDC callback page — handles the redirect back from Keycloak.
 * useAuth hook processes the callback and redirects to home on
 * success. If the callback fails (e.g. the originating tab raced
 * Keycloak end-session and invalidated the code) we fall back to
 * the login screen instead of leaving the user on a stuck spinner.
 */

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

export default function AuthCallback() {
  // useAuth handles the callback automatically when pathname is /auth/callback
  const { isLoading, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      navigate("/auth", { replace: true });
    }
  }, [isLoading, isAuthenticated, navigate]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background">
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="mt-4 text-muted-foreground">{t("auth:loggingIn")}</p>
    </div>
  );
}

