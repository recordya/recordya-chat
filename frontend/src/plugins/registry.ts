/**
 * Plugin registry - runtime plugin discovery from /plugins.
 *
 * Frontend plugins are loaded dynamically from the @plugins alias
 * using the pattern: "{pluginId}/frontend/index.ts".
 *
 * Contract:
 * - Preferred export: registerPlugin()
 * - Backward compatibility: register{PluginIdPascalCase}Plugin()
 */

import { widgetRegistry } from "./WidgetRegistry";

// Re-export core plugin system
export { pluginEventBus } from "./EventBus";
export type {
  PluginEvent,
  PluginEventType,
  WelcomeEventData,
  StatusEventData,
} from "./EventBus";

// SlotRegistry - UI injection points
export { slotRegistry } from "./SlotRegistry";
export type { SlotName, SlotContext, SlotRegistration } from "./SlotRegistry";

// TransformRegistry - message content transformations
export { transformRegistry } from "./TransformRegistry";
export type { TextTransformer, ContentRenderer, TransformContext } from "./TransformRegistry";

// Markdown helper usable by plugin transforms (e.g. strip tables rendered separately)
export { stripMarkdownTables } from "@/utils/markdown";

// ResultRegistry - plugin-driven rendering of tool result payloads
export { resultRegistry } from "./ResultRegistry";
export type {
  ResultRenderer,
  ResultRenderContext,
  ResultRenderDecision,
  ResultRendererAction,
} from "./ResultRegistry";
export { widgetRegistry, extractWidgetDescriptor } from "./WidgetRegistry";
export type {
  WidgetDescriptor,
  WidgetRenderDecision,
  WidgetRenderer,
  WidgetVisibility,
} from "./WidgetRegistry";

// ToolRendererRegistry - plugin-driven rendering of tool arguments / results in ReasoningPanel
export { toolRendererRegistry } from "./ToolRendererRegistry";
export type {
  ToolRenderer,
  ToolRenderContext,
  ToolRenderDecision,
  ToolRenderTarget,
  ToolRenderAction,
} from "./ToolRendererRegistry";

// ViewRegistry - custom plugin views/pages
export { viewRegistry } from "./ViewRegistry";
export type { ViewConfig, ViewProps, NavItem } from "./ViewRegistry";

// FormatConfig - per-plugin locale, duration labels, duration columns
export {
  formatConfigRegistry,
  FormatConfigProvider,
  useFormatConfig,
  NEUTRAL_FORMAT_CONFIG,
} from "./FormatConfig";
export type { PluginFormatConfig, DurationLabels } from "./FormatConfig";

// Plugin SDK - unified API for plugin development
export { createPluginSDK } from "./sdk";
export type {
  PluginSDK,
  SlotOptions,
  ViewOptions,
  TransformOptions,
  ResultRenderOptions,
  WidgetRenderOptions,
  ToolRendererOptions,
  EventHandler,
} from "./sdk";
export { DefaultResultsTableWidget } from "./widgets/DefaultResultsTableWidget";
export { ChoicesWidget } from "./widgets/ChoicesWidget";

type RegisterFunction = () => void | Promise<void>;
type FrontendPluginModule = Record<string, unknown> & {
  registerPlugin?: RegisterFunction;
};

const pluginModuleLoaders = import.meta.glob<FrontendPluginModule>("@plugins/*/frontend/index.{ts,tsx,js,jsx}");
const pluginManifestLoaders = import.meta.glob<string>("@plugins/*/backend/manifest.yaml", {
  query: "?raw",
  import: "default",
});

/**
 * Check if a plugin is enabled in its manifest.
 * Defaults to true if the `enabled` key is missing.
 */
/** @internal — exported for testing */
export function isPluginEnabled(rawManifest: string): boolean {
  for (const rawLine of rawManifest.split(/\r?\n/)) {
    const trimmed = rawLine.replace(/\s+#.*$/, "").trim();
    const match = trimmed.match(/^enabled:\s*(.+)$/);
    if (match) {
      return match[1].trim().toLowerCase() !== "false";
    }
  }
  return true;
}

function parsePublicWidgetsFromManifest(rawManifest: string): string[] {
  const lines = rawManifest.split(/\r?\n/);
  let inFrontendBlock = false;
  let frontendIndent = 0;
  let inPublicWidgetsBlock = false;
  let publicWidgetsIndent = 0;
  const publicWidgets: string[] = [];

  for (const rawLine of lines) {
    const lineWithoutComment = rawLine.replace(/\s+#.*$/, "");
    const trimmed = lineWithoutComment.trim();
    if (!trimmed) {
      continue;
    }
    const indent = lineWithoutComment.length - lineWithoutComment.trimStart().length;

    if (!inFrontendBlock) {
      if (/^frontend:\s*$/.test(trimmed)) {
        inFrontendBlock = true;
        frontendIndent = indent;
      }
      continue;
    }

    if (indent <= frontendIndent && !/^frontend:\s*$/.test(trimmed)) {
      break;
    }

    if (!inPublicWidgetsBlock) {
      if (/^public_widgets:\s*$/.test(trimmed)) {
        inPublicWidgetsBlock = true;
        publicWidgetsIndent = indent;
        continue;
      }
      const inlineMatch = trimmed.match(/^public_widgets:\s*\[(.*)\]\s*$/);
      if (inlineMatch) {
        const values = inlineMatch[1]
          .split(",")
          .map((value) => value.trim().replace(/^['"]|['"]$/g, ""))
          .filter(Boolean);
        publicWidgets.push(...values);
      }
      continue;
    }

    if (indent <= publicWidgetsIndent) {
      break;
    }

    const itemMatch = trimmed.match(/^-\s*(.+)$/);
    if (!itemMatch) {
      continue;
    }
    const widgetType = itemMatch[1].trim().replace(/^['"]|['"]$/g, "");
    if (widgetType) {
      publicWidgets.push(widgetType);
    }
  }

  return publicWidgets;
}

/**
 * Flag to track if plugins have been initialized.
 */
let pluginsInitialized = false;
let pluginsInitializationPromise: Promise<void> | null = null;

/**
 * IDs of plugins discovered, enabled in their manifest, and successfully
 * registered during {@link initializePlugins}.
 */
const initializedPluginIds = new Set<string>();

/**
 * Whether a frontend plugin is enabled and was registered at bootstrap.
 *
 * Lets one plugin gate UI on the presence of another (e.g. a plugin hides
 * controls that depend on another plugin when that other plugin is disabled).
 */
export function isPluginInitialized(pluginId: string): boolean {
  return initializedPluginIds.has(pluginId);
}

function toPascalCase(value: string): string {
  return value
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("");
}

function extractPluginId(modulePath: string): string {
  const match = modulePath.match(/plugins\/([^/]+)\/frontend\/index\.(ts|tsx|js|jsx)$/);
  return match?.[1] ?? modulePath;
}

function resolveRegisterFunction(module: FrontendPluginModule, pluginId: string): RegisterFunction | null {
  if (typeof module.registerPlugin === "function") {
    return module.registerPlugin;
  }

  const legacyName = `register${toPascalCase(pluginId)}Plugin`;
  const legacyRegister = module[legacyName];
  if (typeof legacyRegister === "function") {
    return legacyRegister as RegisterFunction;
  }

  for (const [exportName, exported] of Object.entries(module)) {
    if (
      exportName.startsWith("register") &&
      exportName.endsWith("Plugin") &&
      typeof exported === "function"
    ) {
      return exported as RegisterFunction;
    }
  }

  return null;
}

export async function initializePlugins(): Promise<void> {
  if (pluginsInitialized) {
    console.warn("Plugins already initialized. Skipping.");
    return;
  }

  if (pluginsInitializationPromise) {
    await pluginsInitializationPromise;
    return;
  }

  pluginsInitializationPromise = (async () => {
    const entries = Object.entries(pluginModuleLoaders).sort(([left], [right]) => left.localeCompare(right));

    for (const [modulePath, loadModule] of entries) {
      const pluginId = extractPluginId(modulePath);

      try {
        const manifestPath = modulePath.replace(
          /\/frontend\/index\.(ts|tsx|js|jsx)$/,
          "/backend/manifest.yaml"
        );
        const loadManifest = pluginManifestLoaders[manifestPath];
        if (loadManifest) {
          const rawManifest = await loadManifest();

          if (!isPluginEnabled(rawManifest)) {
            console.info(`Frontend plugin '${pluginId}' disabled in manifest, skipping.`);
            continue;
          }

          const publicWidgets = parsePublicWidgetsFromManifest(rawManifest);
          widgetRegistry.setPluginPublicWidgets(pluginId, publicWidgets);
        } else {
          widgetRegistry.setPluginPublicWidgets(pluginId, []);
        }

        const module = await loadModule();
        const registerPlugin = resolveRegisterFunction(module, pluginId);

        if (!registerPlugin) {
          console.warn(`No register function found for plugin '${pluginId}' (${modulePath}).`);
          continue;
        }

        await registerPlugin();
        initializedPluginIds.add(pluginId);
        console.info(`Frontend plugin '${pluginId}' initialized.`);
      } catch (error) {
        console.error(`Failed to initialize frontend plugin '${pluginId}' (${modulePath}):`, error);
      }
    }

    pluginsInitialized = true;
  })();

  try {
    await pluginsInitializationPromise;
  } finally {
    pluginsInitializationPromise = null;
  }
}

export function resetPluginInitialization(): void {
  pluginsInitialized = false;
  pluginsInitializationPromise = null;
  initializedPluginIds.clear();
}
