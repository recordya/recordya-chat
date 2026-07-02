import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";

import { getLocale, loadConfig } from "@/lib/config";
import { initI18n } from "@/i18n";
// Initialize plugins before rendering
import { initializePlugins } from "@/plugins/registry";

function applyDocumentI18n(i18n: ReturnType<typeof initI18n>): void {
  const title = i18n.t("common:appTitle");
  const description = i18n.t("common:appDescription");

  document.documentElement.lang = i18n.language || "en";
  document.title = title;
  document.querySelector('meta[name="description"]')?.setAttribute("content", description);
  document.querySelector('meta[property="og:title"]')?.setAttribute("content", title);
  document.querySelector('meta[property="og:description"]')?.setAttribute("content", description);
}

async function bootstrap(): Promise<void> {
  try {
    await loadConfig();
  } catch (error) {
    console.warn("Config loading failed, using defaults:", error);
  }

  // Initialize i18n with the resolved, static locale before rendering.
  applyDocumentI18n(initI18n(getLocale()));

  try {
    await initializePlugins();
  } catch (error) {
    console.error("Plugin bootstrap failed:", error);
  }

  createRoot(document.getElementById("root")!).render(<App />);
}

void bootstrap();
