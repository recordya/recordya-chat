/**
 * Utility functions for formatting values in tables and displays.
 *
 * All locale- and language-specific behaviour (number locale, duration label
 * words, set of duration fields) is supplied by the caller via {@link FormatValueOptions}.
 * The plugin owns those values and provides them through the format config registry.
 */

import type { DurationLabels } from "@/plugins/FormatConfig";

export interface FormatValueOptions {
  /** BCP 47 locale used for `Number.prototype.toLocaleString`. */
  locale: string;
  /** Words appended after the hour and minute parts in `formatDuration`. */
  durationLabels: DurationLabels;
  /** Output field names that should be rendered as durations (in minutes). */
  durationFields?: readonly string[];
}

/**
 * Format duration from minutes to human-readable string.
 */
export function formatDuration(totalMinutes: number, labels: DurationLabels): string {
  const minutesRounded = Math.max(0, Math.round(totalMinutes));
  const hours = Math.floor(minutesRounded / 60);
  const mins = minutesRounded % 60;
  if (hours === 0) return `${mins} ${labels.minute}`;
  if (mins === 0) return `${hours} ${labels.hour}`;
  return `${hours} ${labels.hour} ${mins} ${labels.minute}`;
}

/**
 * Coerce a value to a number if possible. Accepts comma as a decimal separator
 * to handle PostgreSQL numeric strings emitted in locales such as pl-PL or de-DE.
 */
export function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed.replace(",", "."));
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

/**
 * Check whether the given field name should be rendered as a duration.
 */
export function isDurationField(
  fieldName: string | undefined,
  durationFields: readonly string[] | undefined
): boolean {
  if (!fieldName || !durationFields || durationFields.length === 0) return false;
  return durationFields.includes(fieldName);
}

/**
 * Format a number for display.
 * - Integers display without decimals
 * - Decimals display with 1 decimal place
 */
export function formatNumber(num: number, locale: string): string {
  if (Number.isInteger(num) || Math.abs(num - Math.round(num)) < 0.0001) {
    return Math.round(num).toLocaleString(locale);
  }
  return num.toLocaleString(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

/**
 * Format a value for display in tables. Routing rules:
 * - null/undefined → em dash
 * - duration field (per {@link FormatValueOptions.durationFields}) → `formatDuration`
 * - numbers and numeric strings → `formatNumber` with the configured locale
 * - everything else → `String(value)`
 */
export function formatValue(
  value: unknown,
  fieldName: string | undefined,
  options: FormatValueOptions
): string {
  if (value === null || value === undefined) return "—";

  if (isDurationField(fieldName, options.durationFields)) {
    const n = coerceNumber(value);
    if (n !== null) return formatDuration(n, options.durationLabels);
  }

  if (typeof value === "number") {
    return formatNumber(value, options.locale);
  }

  if (typeof value === "string" && !isNaN(Number(value))) {
    return formatNumber(Number(value), options.locale);
  }

  return String(value);
}

/**
 * Format a field label for display.
 * - If the key contains a space, treat it as a ready-made label from a SQL alias
 *   (e.g. `AS "Total count"`) and return it unchanged.
 * - Otherwise convert snake_case / camelCase to Title Case.
 */
export function formatLabel(key: string): string {
  if (key.includes(" ")) return key;
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
