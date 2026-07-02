import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { readdirSync } from "node:fs";
import { createRequire } from "module";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const require = createRequire(__filename);

// Plugins live in a sibling plugins/ directory (next to core/), shared by both
// Docker Compose (mounted to /plugins) and manual local runs. The CI frontend
// build instead stages a *filtered* plugin subset into core/plugins; when such
// staged packages are present they take precedence, so example_customer builds bundle
// only their selected plugins. A core/plugins holding just a .gitkeep does not
// count — it falls through to the sibling.
const SIBLING_PLUGINS_DIR = path.resolve(__dirname, "../../plugins");
const LOCAL_PLUGINS_DIR = path.resolve(__dirname, "../plugins");

function hasPluginPackages(dir: string): boolean {
  try {
    return readdirSync(dir, { withFileTypes: true }).some(
      (entry) => entry.isDirectory() && !entry.name.startsWith("."),
    );
  } catch {
    return false;
  }
}

const PLUGINS_DIR = hasPluginPackages(LOCAL_PLUGINS_DIR) ? LOCAL_PLUGINS_DIR : SIBLING_PLUGINS_DIR;

function isBareImport(source: string): boolean {
  return !source.startsWith(".") && !source.startsWith("/") && !source.startsWith("\0");
}

function normalizeToFilePath(importer: string): string {
  // Vite can pass importer as:
  // - regular absolute path
  // - @fs-prefixed absolute path
  // - file:// URL
  if (importer.startsWith("file://")) {
    return fileURLToPath(importer);
  }

  const withoutFsPrefix = importer.startsWith("/@fs/")
    ? importer.slice("/@fs/".length)
    : importer;
  return path.normalize(withoutFsPrefix);
}

function isImporterInPluginsDir(importer: string): boolean {
  const pluginsDir = PLUGINS_DIR;
  const importerPath = normalizeToFilePath(importer);
  const relative = path.relative(pluginsDir, importerPath);

  // Path is inside plugins dir when it's not absolute upward traversal.
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

// https://vitejs.dev/config/
export default defineConfig({
  test: {
    setupFiles: ["src/test/setup.ts"],
    include: [
      "src/**/*.{test,spec}.?(c|m)[jt]s?(x)",
      "../../plugins/*/frontend/**/*.{test,spec}.?(c|m)[jt]s?(x)",
      "/plugins/*/frontend/**/*.{test,spec}.?(c|m)[jt]s?(x)",
    ],
  },
  server: {
    host: "::",
    port: 8080,
  },
  plugins: [
    react(),
    {
      name: "resolve-plugin-bare-imports-from-frontend-node_modules",
      resolveId(source, importer) {
        if (!importer || !isImporterInPluginsDir(importer)) {
          return null;
        }

        if (!isBareImport(source)) {
          return null;
        }

        if (source.startsWith("@/") || source.startsWith("@plugins/")) {
          return null;
        }

        try {
          return require.resolve(source, {
            paths: [path.resolve(__dirname, "./node_modules")],
          });
        } catch {
          return null;
        }
      },
    },
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@plugins": PLUGINS_DIR,
      // Ensure plugins use the same React instance
      "react": path.resolve(__dirname, "./node_modules/react"),
      "react-dom": path.resolve(__dirname, "./node_modules/react-dom"),
      "lucide-react": path.resolve(__dirname, "./node_modules/lucide-react"),
    },
    dedupe: ["react", "react-dom", "@tanstack/react-query", "sonner", "next-themes"],
  },
});
