export type ToolHistoryEntry = {
  tool: string;
  result: Record<string, unknown>;
};

export type ExtractedToolData = {
  sql: string | null;
  mode: "predefined" | "dynamic" | null;
  queryResults: any[] | null;
};

type SuccessfulToolResult = {
  success: true;
  sql?: string;
  result?: unknown;
};

function isWidgetRow(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const row = value as Record<string, unknown>;
  const widgetType = row._widget_type;
  return typeof widgetType === "string" && widgetType.trim().length > 0;
}

function hasWidgetResult(result: unknown): result is Record<string, unknown>[] {
  return Array.isArray(result) && result.some((item) => isWidgetRow(item));
}

export function extractFromToolHistory(
  toolHistory: ToolHistoryEntry[]
): ExtractedToolData {
  let latestSuccessful: { tool: string; result: SuccessfulToolResult } | null = null;

  for (let i = toolHistory.length - 1; i >= 0; i--) {
    const tool = toolHistory[i];
    const toolResult = tool.result as SuccessfulToolResult;
    if (toolResult.success !== true) {
      continue;
    }

    if (!latestSuccessful) {
      latestSuccessful = { tool: tool.tool, result: toolResult };
    }

    if (hasWidgetResult(toolResult.result)) {
      const mode = tool.tool === "generate_custom_sql" ? "dynamic" : "predefined";
      return {
        sql: toolResult.sql || null,
        mode,
        queryResults: toolResult.result,
      };
    }
  }

  if (latestSuccessful) {
    const mode = latestSuccessful.tool === "generate_custom_sql" ? "dynamic" : "predefined";
    return {
      sql: latestSuccessful.result.sql || null,
      mode,
      queryResults: Array.isArray(latestSuccessful.result.result)
        ? latestSuccessful.result.result
        : null,
    };
  }

  return { sql: null, mode: null, queryResults: null };
}
