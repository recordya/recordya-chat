import { afterEach, describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { initI18n, resources } from ".";

const pluralSuffixes = new Set(["one", "two", "few", "many", "other", "zero"]);

function flattenBaseKeys(value: unknown, prefix = ""): Set<string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return new Set(prefix ? [baseKey(prefix)] : []);
  }
  return Object.entries(value).reduce((keys, [key, child]) => {
    const nextPrefix = prefix ? `${prefix}.${key}` : key;
    for (const childKey of flattenBaseKeys(child, nextPrefix)) {
      keys.add(childKey);
    }
    return keys;
  }, new Set<string>());
}

function baseKey(key: string): string {
  const parts = key.split(".");
  const last = parts[parts.length - 1];
  const underscore = last.lastIndexOf("_");
  if (underscore === -1) return key;
  const suffix = last.slice(underscore + 1);
  if (!pluralSuffixes.has(suffix)) return key;
  return [...parts.slice(0, -1), last.slice(0, underscore)].join(".");
}

function walkFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (["locales", "test"].includes(entry.name)) return [];
      return walkFiles(path);
    }
    return /\.[cm]?[tj]sx?$/.test(entry.name) ? [path] : [];
  });
}

describe("frontend i18n resources", () => {
  afterEach(() => {
    initI18n("en");
  });

  it("normalizes supported and unknown locales", () => {
    expect(initI18n(" PL ").language).toBe("pl");
    expect(initI18n("de").language).toBe("en");
  });

  it("keeps English and Polish catalog base keys aligned", () => {
    const languages = resources as Record<string, Record<string, unknown>>;
    for (const namespace of Object.keys(languages.en)) {
      expect(flattenBaseKeys(languages.pl[namespace])).toEqual(flattenBaseKeys(languages.en[namespace]));
    }
  });

  it("defines every ns:key used by core frontend code", () => {
    const languages = resources as Record<string, Record<string, unknown>>;
    const keysByNamespace = Object.fromEntries(
      Object.entries(languages.en).map(([namespace, catalog]) => [namespace, flattenBaseKeys(catalog)]),
    );
    const srcRoot = fileURLToPath(new URL("../", import.meta.url));
    const missing: string[] = [];

    for (const file of walkFiles(srcRoot)) {
      const text = readFileSync(file, "utf8");
      const patterns = [
        /(?:t|i18n\.t)\(\s*["']([a-z]+):([^"']+)["']/g,
        /i18nKey\s*=\s*["']([a-z]+):([^"']+)["']/g,
      ];
      for (const pattern of patterns) {
        for (const match of text.matchAll(pattern)) {
          const namespace = match[1];
          const key = baseKey(match[2]);
          if (!keysByNamespace[namespace]?.has(key)) {
            missing.push(`${relative(srcRoot, file)} -> ${namespace}:${key}`);
          }
        }
      }
    }

    expect(missing).toEqual([]);
  });
});
