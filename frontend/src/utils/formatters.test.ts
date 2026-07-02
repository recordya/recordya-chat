import { describe, it, expect } from "vitest";
import {
  formatValue,
  formatDuration,
  formatNumber,
  formatLabel,
  coerceNumber,
  isDurationField,
  type FormatValueOptions,
} from "./formatters";

const NEUTRAL_LABELS = { hour: "h", minute: "min" };
const NEUTRAL_OPTIONS: FormatValueOptions = {
  locale: "en-US",
  durationLabels: NEUTRAL_LABELS,
};

describe("formatValue", () => {
  it("returns dash for null/undefined", () => {
    expect(formatValue(null, undefined, NEUTRAL_OPTIONS)).toBe("—");
    expect(formatValue(undefined, undefined, NEUTRAL_OPTIONS)).toBe("—");
  });

  it("formats whole numbers without decimals", () => {
    expect(formatValue(5, undefined, NEUTRAL_OPTIONS)).toBe("5");
    expect(formatValue(100, undefined, NEUTRAL_OPTIONS)).toBe("100");
    expect(formatValue(1000, undefined, NEUTRAL_OPTIONS)).toBe("1,000");
  });

  it("formats numbers that are effectively integers (within tolerance)", () => {
    expect(formatValue(5.0, undefined, NEUTRAL_OPTIONS)).toBe("5");
    expect(formatValue(10.00009, undefined, NEUTRAL_OPTIONS)).toBe("10");
  });

  it("crosses the integer-tolerance boundary", () => {
    expect(formatValue(10.0002, undefined, NEUTRAL_OPTIONS)).toBe("10.0");
  });

  it("formats decimals with 1 decimal place (with rounding)", () => {
    expect(formatValue(3.7, undefined, NEUTRAL_OPTIONS)).toBe("3.7");
    expect(formatValue(3.75, undefined, NEUTRAL_OPTIONS)).toBe("3.8");
    expect(formatValue(3.74, undefined, NEUTRAL_OPTIONS)).toBe("3.7");
  });

  it("shows .0 decimals when rounded to 1 place", () => {
    expect(formatValue(5.04, undefined, NEUTRAL_OPTIONS)).toBe("5.0");
  });

  it("handles string integers and decimals (PostgreSQL numeric)", () => {
    expect(formatValue("5", undefined, NEUTRAL_OPTIONS)).toBe("5");
    expect(formatValue("5.0000000000000000", undefined, NEUTRAL_OPTIONS)).toBe("5");
    expect(formatValue("3.7142857142857143", undefined, NEUTRAL_OPTIONS)).toBe("3.7");
    expect(formatValue("12.5", undefined, NEUTRAL_OPTIONS)).toBe("12.5");
  });

  it("returns non-numeric strings as-is", () => {
    expect(formatValue("Hello", undefined, NEUTRAL_OPTIONS)).toBe("Hello");
    expect(formatValue("Hello world", undefined, NEUTRAL_OPTIONS)).toBe("Hello world");
  });

  it("formats duration field listed in options", () => {
    const options: FormatValueOptions = { ...NEUTRAL_OPTIONS, durationFields: ["total_minutes"] };
    expect(formatValue(90, "total_minutes", options)).toBe("1 h 30 min");
  });

  it("uses configured duration labels", () => {
    const options: FormatValueOptions = {
      locale: "en-US",
      durationLabels: { hour: "hr", minute: "m" },
      durationFields: ["dur"],
    };
    expect(formatValue(150, "dur", options)).toBe("2 hr 30 m");
  });

  it("falls back to numeric formatting when field is not in durationFields", () => {
    expect(formatValue(90, "total_minutes", NEUTRAL_OPTIONS)).toBe("90");
  });
});

describe("formatNumber", () => {
  it("uses the supplied locale for thousand separators", () => {
    // pl-PL applies grouping starting at 5-digit numbers (CLDR minimumGroupingDigits=2),
    // so we test with 10_000 to exercise the locale-specific U+00A0 separator.
    expect(formatNumber(10000, "en-US")).toBe("10,000");
    expect(formatNumber(10000, "pl-PL")).toBe("10\u00A0000");
    expect(formatNumber(10000, "de-DE")).toBe("10.000");
  });
});

describe("formatDuration", () => {
  it("formats minutes only", () => {
    expect(formatDuration(30, NEUTRAL_LABELS)).toBe("30 min");
    expect(formatDuration(59, NEUTRAL_LABELS)).toBe("59 min");
  });

  it("formats hours only", () => {
    expect(formatDuration(60, NEUTRAL_LABELS)).toBe("1 h");
    expect(formatDuration(120, NEUTRAL_LABELS)).toBe("2 h");
  });

  it("formats hours and minutes", () => {
    expect(formatDuration(90, NEUTRAL_LABELS)).toBe("1 h 30 min");
    expect(formatDuration(150, NEUTRAL_LABELS)).toBe("2 h 30 min");
  });

  it("handles zero and clamps negatives to 0", () => {
    expect(formatDuration(0, NEUTRAL_LABELS)).toBe("0 min");
    expect(formatDuration(-10, NEUTRAL_LABELS)).toBe("0 min");
  });
});

describe("formatLabel", () => {
  it("converts snake_case to Title Case", () => {
    expect(formatLabel("user_name")).toBe("User Name");
    expect(formatLabel("total_count")).toBe("Total Count");
  });

  it("handles camelCase", () => {
    expect(formatLabel("averagePosition")).toBe("Average Position");
  });

  it("handles single words", () => {
    expect(formatLabel("title")).toBe("Title");
  });

  it("returns labels containing spaces unchanged", () => {
    expect(formatLabel("Total count")).toBe("Total count");
    expect(formatLabel("Average value")).toBe("Average value");
  });

  it("handles Polish diacritics without capitalizing mid-word characters", () => {
    expect(formatLabel("nowości")).toBe("Nowości");
  });
});

describe("coerceNumber", () => {
  it("returns number for valid numbers and parses string numbers", () => {
    expect(coerceNumber(5)).toBe(5);
    expect(coerceNumber(3.14)).toBe(3.14);
    expect(coerceNumber("5")).toBe(5);
    expect(coerceNumber("3.14")).toBe(3.14);
    expect(coerceNumber("3,14")).toBe(3.14);
  });

  it("returns null for invalid or empty values", () => {
    expect(coerceNumber("hello")).toBe(null);
    expect(coerceNumber("")).toBe(null);
    expect(coerceNumber(null)).toBe(null);
    expect(coerceNumber(undefined)).toBe(null);
  });
});

describe("isDurationField", () => {
  it("returns false when no duration fields are configured", () => {
    expect(isDurationField("total_minutes", undefined)).toBe(false);
    expect(isDurationField("total_minutes", [])).toBe(false);
  });

  it("returns true when field is in the list, false otherwise", () => {
    expect(isDurationField("total_minutes", ["total_minutes"])).toBe(true);
    expect(isDurationField("title", ["total_minutes"])).toBe(false);
    expect(isDurationField(undefined, ["total_minutes"])).toBe(false);
  });
});
