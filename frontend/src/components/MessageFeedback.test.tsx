import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { MessageFeedback } from "./MessageFeedback";
import type { ChatMessageFeedbackResponse } from "@/lib/api";
import { initI18n } from "@/i18n";
import { toCreateMessageFeedbackRequest } from "@/utils/messageFeedback";

const positiveFeedback: ChatMessageFeedbackResponse = {
  id: "feedback-1",
  message_id: "message-1",
  chat_id: "chat-1",
  rating: "positive",
  saved_time: "up_to_30_min",
  comment: "Helpful",
  created_at: "2026-06-24T10:00:00Z",
  updated_at: "2026-06-24T10:00:00Z",
};

describe("MessageFeedback", () => {
  afterEach(() => {
    initI18n("en");
  });

  it("renders positive and negative feedback controls in English by default", () => {
    const html = renderToStaticMarkup(<MessageFeedback />);

    expect(html).toContain("Rate positively");
    expect(html).toContain("Rate negatively");
  });

  it("marks initial persisted positive feedback as selected", () => {
    const html = renderToStaticMarkup(
      <MessageFeedback
        chatId="chat-1"
        messageId="message-1"
        initialFeedback={positiveFeedback}
      />,
    );

    expect(html).toContain('aria-label="Rate positively"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('aria-label="Rate negatively"');
    expect(html).toContain('aria-pressed="false"');
  });

  it("builds positive feedback API payload with saved time", () => {
    expect(
      toCreateMessageFeedbackRequest({
        rating: "positive",
        savedTime: "up_to_30_min",
        comment: "Helpful",
      }),
    ).toEqual({
      rating: "positive",
      saved_time: "up_to_30_min",
      comment: "Helpful",
    });
  });

  it("builds negative feedback API payload without saved time", () => {
    expect(
      toCreateMessageFeedbackRequest({
        rating: "negative",
        savedTime: "up_to_1h",
        comment: "Wrong answer",
      }),
    ).toEqual({
      rating: "negative",
      saved_time: null,
      comment: "Wrong answer",
    });
  });
});
