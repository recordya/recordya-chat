/**
 * Vitest global setup.
 *
 * Initializes i18next synchronously with the default (en) locale so that
 * components rendered in tests (including SSR via renderToStaticMarkup) have
 * translations available without async hydration.
 */
import { initI18n } from "@/i18n";

initI18n("en");
