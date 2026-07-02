/**
 * Per-plugin formatting configuration.
 *
 * Core ships with a language-neutral default. Each plugin owns its locale,
 * duration label words, and the list of database columns that hold durations.
 * The active config is selected per chat message based on `sourcePluginId`
 * and exposed to render-tree components via {@link FormatConfigProvider}.
 */

import { createContext, useContext } from "react";

export interface DurationLabels {
  hour: string;
  minute: string;
}

export interface PluginFormatConfig {
  /** BCP 47 locale used for `Number.prototype.toLocaleString`. */
  locale: string;
  /** Words appended after the hour and minute parts in `formatDuration`. */
  durationLabels: DurationLabels;
  /** Database column names whose values are durations expressed in minutes. */
  durationColumnNames: readonly string[];
}

export const NEUTRAL_FORMAT_CONFIG: PluginFormatConfig = {
  locale: "en-US",
  durationLabels: { hour: "h", minute: "min" },
  durationColumnNames: [],
};

class FormatConfigRegistry {
  private configs = new Map<string, PluginFormatConfig>();

  register(pluginId: string, config: PluginFormatConfig): void {
    this.configs.set(pluginId, config);
  }

  unregister(pluginId: string): void {
    this.configs.delete(pluginId);
  }

  get(pluginId: string | undefined): PluginFormatConfig {
    if (!pluginId) return NEUTRAL_FORMAT_CONFIG;
    return this.configs.get(pluginId) ?? NEUTRAL_FORMAT_CONFIG;
  }
}

export const formatConfigRegistry = new FormatConfigRegistry();

const FormatConfigContext = createContext<PluginFormatConfig>(NEUTRAL_FORMAT_CONFIG);

export const FormatConfigProvider = FormatConfigContext.Provider;

export function useFormatConfig(): PluginFormatConfig {
  return useContext(FormatConfigContext);
}
