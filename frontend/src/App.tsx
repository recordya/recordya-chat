import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { ModelSettingsProvider } from "@/contexts/ModelSettingsContext";
import { queryClient } from "@/lib/queryClient";
import { viewRegistry } from "@/plugins/registry";
import Index from "./pages/Index";
import Auth from "./pages/Auth";
import AuthCallback from "./pages/AuthCallback";
import NotFound from "./pages/NotFound";

/**
 * Get dynamic routes from ViewRegistry.
 * Plugin views render inside Index (which provides IconRail + layout).
 */
function getPluginRoutes() {
  return viewRegistry.getRoutes().map(({ path }) => (
    <Route key={path} path={path} element={<ProtectedRoute><Index /></ProtectedRoute>} />
  ));
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/auth" replace />;
  }

  return <>{children}</>;
}

function AuthRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

const App = () => {
  // Get plugin routes dynamically
  const pluginRoutes = getPluginRoutes();

  return (
    <QueryClientProvider client={queryClient}>
      <ModelSettingsProvider>
        <TooltipProvider>
          <Toaster />
          <Sonner />
          <BrowserRouter>
            <Routes>
              <Route path="/auth" element={<AuthRoute><Auth /></AuthRoute>} />
              <Route path="/auth/callback" element={<AuthCallback />} />
              <Route path="/" element={<ProtectedRoute><Index /></ProtectedRoute>} />
              <Route path="/c/:chatId" element={<ProtectedRoute><Index /></ProtectedRoute>} />
              {/* Plugin routes from ViewRegistry */}
              {pluginRoutes}
              {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </BrowserRouter>
        </TooltipProvider>
      </ModelSettingsProvider>
    </QueryClientProvider>
  );
};

export default App;
