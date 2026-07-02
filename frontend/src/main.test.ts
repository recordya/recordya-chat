import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock all heavy dependencies so we can test bootstrap() in isolation.
const mockLoadConfig = vi.fn().mockResolvedValue(undefined);
const mockGetLocale = vi.fn(() => "en");
const mockInitializePlugins = vi.fn().mockResolvedValue(undefined);
const mockI18n = {
  language: "en",
  t: vi.fn((key: string) =>
    key === "common:appTitle"
      ? "Knowledge Base"
      : key === "common:appDescription"
        ? "Intelligent data analysis. Ask questions in natural language."
        : key,
  ),
};
const mockInitI18n = vi.fn(() => mockI18n);
const mockRender = vi.fn();
const mockCreateRoot = vi.fn(() => ({ render: mockRender }));

vi.mock("@/lib/config", () => ({ loadConfig: mockLoadConfig, getLocale: mockGetLocale }));
vi.mock("@/i18n", () => ({ initI18n: mockInitI18n }));
vi.mock("@/plugins/registry", () => ({ initializePlugins: mockInitializePlugins }));
vi.mock("react-dom/client", () => ({ createRoot: mockCreateRoot }));
vi.mock("./App.tsx", () => ({ default: "MockApp" }));
vi.mock("./index.css", () => ({}));

describe("bootstrap (main.tsx)", () => {
  let fakeDocument: {
    documentElement: { lang: string };
    title: string;
    getElementById: ReturnType<typeof vi.fn>;
    querySelector: ReturnType<typeof vi.fn>;
  };
  let descriptionMeta: { setAttribute: ReturnType<typeof vi.fn> };
  let ogTitleMeta: { setAttribute: ReturnType<typeof vi.fn> };
  let ogDescriptionMeta: { setAttribute: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    vi.clearAllMocks();
    const fakeRoot = {};
    descriptionMeta = { setAttribute: vi.fn() };
    ogTitleMeta = { setAttribute: vi.fn() };
    ogDescriptionMeta = { setAttribute: vi.fn() };
    fakeDocument = {
      documentElement: { lang: "" },
      title: "",
      getElementById: vi.fn().mockReturnValue(fakeRoot),
      querySelector: vi.fn((selector: string) => {
        if (selector === 'meta[name="description"]') return descriptionMeta;
        if (selector === 'meta[property="og:title"]') return ogTitleMeta;
        if (selector === 'meta[property="og:description"]') return ogDescriptionMeta;
        return null;
      }),
    };
    vi.stubGlobal("document", {
      ...fakeDocument,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  async function runBootstrap(): Promise<void> {
    // Dynamic import triggers top-level `void bootstrap()`
    await import("./main");
    // Flush microtasks so the async bootstrap() settles
    await new Promise((r) => setTimeout(r, 0));
  }

  it("initializes i18n after config and before plugins", async () => {
    const callOrder: string[] = [];
    mockLoadConfig.mockImplementation(async () => { callOrder.push("loadConfig"); });
    mockInitI18n.mockImplementationOnce(() => {
      callOrder.push("initI18n");
      return mockI18n;
    });
    mockInitializePlugins.mockImplementation(async () => { callOrder.push("initializePlugins"); });

    await runBootstrap();

    expect(mockLoadConfig).toHaveBeenCalledOnce();
    expect(mockInitI18n).toHaveBeenCalledWith("en");
    expect(mockInitializePlugins).toHaveBeenCalledOnce();
    expect(callOrder).toEqual(["loadConfig", "initI18n", "initializePlugins"]);
  });

  it("updates static document language and metadata from i18n", async () => {
    await runBootstrap();

    expect(fakeDocument.documentElement.lang).toBe("en");
    expect(document.title).toBe("Knowledge Base");
    expect(descriptionMeta.setAttribute).toHaveBeenCalledWith(
      "content",
      "Intelligent data analysis. Ask questions in natural language.",
    );
    expect(ogTitleMeta.setAttribute).toHaveBeenCalledWith("content", "Knowledge Base");
    expect(ogDescriptionMeta.setAttribute).toHaveBeenCalledWith(
      "content",
      "Intelligent data analysis. Ask questions in natural language.",
    );
  });

  it("calls createRoot and render after config and plugins are loaded", async () => {
    await runBootstrap();

    expect(mockCreateRoot).toHaveBeenCalledOnce();
    expect(mockRender).toHaveBeenCalledOnce();
  });

  it("still renders when initializePlugins throws", async () => {
    vi.stubGlobal("console", { ...console, error: vi.fn() });
    mockInitializePlugins.mockRejectedValueOnce(new Error("plugin boom"));

    await runBootstrap();

    expect(mockRender).toHaveBeenCalledOnce();
    expect(console.error).toHaveBeenCalledWith(
      "Plugin bootstrap failed:",
      expect.any(Error)
    );
  });

  it("still renders when loadConfig throws", async () => {
    vi.stubGlobal("console", { ...console, warn: vi.fn() });
    mockLoadConfig.mockRejectedValueOnce(new Error("config boom"));

    await runBootstrap();

    expect(mockRender).toHaveBeenCalledOnce();
    expect(mockInitializePlugins).toHaveBeenCalledOnce();
    expect(console.warn).toHaveBeenCalledWith(
      "Config loading failed, using defaults:",
      expect.any(Error)
    );
  });
});

