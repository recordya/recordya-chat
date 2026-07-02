import { describe, expect, it } from "vitest";
import { extractFromToolHistory, type ToolHistoryEntry } from "./toolHistory";

describe("extractFromToolHistory", () => {
  it("returns latest successful non-widget result when no widget payload exists", () => {
    const history: ToolHistoryEntry[] = [
      {
        tool: "get_predefined_sql",
        result: {
          success: true,
          sql: "select 1",
          result: [{ value: 1 }],
        },
      },
      {
        tool: "generate_custom_sql",
        result: {
          success: true,
          sql: "select 2",
          result: [{ value: 2 }],
        },
      },
    ];

    expect(extractFromToolHistory(history)).toEqual({
      sql: "select 2",
      mode: "dynamic",
      queryResults: [{ value: 2 }],
    });
  });

  it("prefers last successful widget payload over later non-widget success", () => {
    const history: ToolHistoryEntry[] = [
      {
        tool: "make_choices",
        result: {
          success: true,
          result: [
            {
              _widget_type: "make_choices",
              _widget_payload: {
                questions: [{ id: "q1", prompt: "Pytanie", options: [{ id: "o1", label: "Opcja" }] }],
              },
            },
          ],
        },
      },
      {
        tool: "some_other_tool",
        result: {
          success: true,
          result: [{ value: "later-but-not-widget" }],
        },
      },
    ];

    expect(extractFromToolHistory(history)).toEqual({
      sql: null,
      mode: "predefined",
      queryResults: [
        {
          _widget_type: "make_choices",
          _widget_payload: {
            questions: [{ id: "q1", prompt: "Pytanie", options: [{ id: "o1", label: "Opcja" }] }],
          },
        },
      ],
    });
  });
});
