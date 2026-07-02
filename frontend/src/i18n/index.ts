/**
 * i18next initialization.
 *
 * The locale is static and config-driven: it is resolved once from the backend
 * (see lib/config.ts -> getLocale) and applied at bootstrap before the app
 * renders. There is no runtime language switching and no browser detection.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enCommon from "./locales/en/common.json";
import enAuth from "./locales/en/auth.json";
import enChat from "./locales/en/chat.json";
import enSettings from "./locales/en/settings.json";
import enErrors from "./locales/en/errors.json";
import enReasoning from "./locales/en/reasoning.json";

import plCommon from "./locales/pl/common.json";
import plAuth from "./locales/pl/auth.json";
import plChat from "./locales/pl/chat.json";
import plSettings from "./locales/pl/settings.json";
import plErrors from "./locales/pl/errors.json";
import plReasoning from "./locales/pl/reasoning.json";

export const defaultNS = "common";

export const namespaces = [
  "common",
  "auth",
  "chat",
  "settings",
  "errors",
  "reasoning",
] as const;

export const resources = {
  en: {
    common: enCommon,
    auth: enAuth,
    chat: enChat,
    settings: enSettings,
    errors: enErrors,
    reasoning: enReasoning,
  },
  pl: {
    common: plCommon,
    auth: plAuth,
    chat: plChat,
    settings: plSettings,
    errors: plErrors,
    reasoning: plReasoning,
  },
} as const;

/** Normalize any incoming value to a supported locale (fallback: en). */
function resolveLocale(locale?: string): "en" | "pl" {
  return locale?.trim().toLowerCase() === "pl" ? "pl" : "en";
}

/**
 * Initialize i18next with the resolved locale. Resources are bundled inline,
 * so initialization is synchronous and safe for SSR-style rendering in tests.
 */
export function initI18n(locale?: string): typeof i18n {
  const lng = resolveLocale(locale);
  if (i18n.isInitialized) {
    if (i18n.language !== lng) {
      void i18n.changeLanguage(lng);
    }
    return i18n;
  }
  void i18n.use(initReactI18next).init({
    resources,
    lng,
    fallbackLng: "en",
    ns: [...namespaces],
    defaultNS,
    interpolation: { escapeValue: false },
    returnNull: false,
    react: { useSuspense: false },
  });
  return i18n;
}

export default i18n;
