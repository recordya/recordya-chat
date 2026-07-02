import { describe, expect, it } from "vitest";
import type { Message } from "@/components/ChatMessage";
import { mergeMessage, removeMessage, upsertMessage } from "./streamingMessages";

const userMessage: Message = {
  id: "user-1",
  role: "user",
  content: "Show me documents",
};

describe("streamingMessages", () => {
  it("updates streamed assistant content in place", () => {
    const streamingMessage: Message = {
      id: "assistant-stream-1",
      role: "assistant",
      content: "Partial",
      sourcePluginId: "search",
    };

    const withPartial = mergeMessage([userMessage], streamingMessage);
    const withNextChunk = mergeMessage(withPartial, {
      ...streamingMessage,
      content: "Partial answer",
      reasoningSteps: [
        {
          toolId: "tool-1",
          toolName: "lookup_items",
          reasoning: "Looking up relevant items",
          message: "Looking up relevant items",
          arguments: { query: "items" },
          iteration: 1,
          status: "running",
        },
      ],
    });

    expect(withNextChunk).toHaveLength(2);
    expect(withNextChunk[1]).toMatchObject({
      id: "assistant-stream-1",
      role: "assistant",
      content: "Partial answer",
      sourcePluginId: "search",
    });
    expect(withNextChunk[1].reasoningSteps).toHaveLength(1);
  });

  it("finalizes the streamed assistant message without adding a duplicate", () => {
    const streamingMessage: Message = {
      id: "assistant-stream-1",
      role: "assistant",
      content: "Partial answer",
    };
    const finalMessage: Message = {
      id: "assistant-stream-1",
      role: "assistant",
      content: "Final answer",
      queryResults: [{ _widget_type: "source_cards" }],
      toolResults: [
        {
          tool: "render_items",
          arguments: {},
          result: { success: true },
        },
      ],
    };

    const messages = upsertMessage([userMessage, streamingMessage], finalMessage);

    expect(messages).toHaveLength(2);
    expect(messages[1]).toEqual(finalMessage);
    expect(messages.map((message) => message.id)).toEqual([
      "user-1",
      "assistant-stream-1",
    ]);
  });

  it("removes an empty streaming placeholder on abort", () => {
    const streamingMessage: Message = {
      id: "assistant-stream-1",
      role: "assistant",
      content: "",
    };

    expect(removeMessage([userMessage, streamingMessage], "assistant-stream-1")).toEqual([
      userMessage,
    ]);
  });
});
