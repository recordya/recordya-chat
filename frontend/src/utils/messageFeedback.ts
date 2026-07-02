import type { CreateMessageFeedbackRequest, MessageFeedbackRating } from "@/lib/api";

export interface MessageFeedbackPayload {
  rating: MessageFeedbackRating;
  savedTime: string | null;
  comment: string | null;
}

export function toCreateMessageFeedbackRequest({
  rating,
  savedTime,
  comment,
}: MessageFeedbackPayload): CreateMessageFeedbackRequest {
  return {
    rating,
    saved_time: rating === "positive" ? savedTime : null,
    comment,
  };
}