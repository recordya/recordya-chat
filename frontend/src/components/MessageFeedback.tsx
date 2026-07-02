import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  createMessageFeedback,
  type ChatMessageFeedbackResponse,
  type MessageFeedbackRating,
} from "@/lib/api";
import {
  toCreateMessageFeedbackRequest,
  type MessageFeedbackPayload,
} from "@/utils/messageFeedback";

interface FeedbackActionProps {
  rating: MessageFeedbackRating;
  currentFeedback: ChatMessageFeedbackResponse | null;
  onSubmit: (payload: MessageFeedbackPayload) => Promise<void>;
}

const feedbackConfig = {
  positive: {
    labelKey: "chat:feedbackPositiveLabel",
    titleKey: "chat:feedbackPositiveTitle",
    Icon: ThumbsUp,
  },
  negative: {
    labelKey: "chat:feedbackNegativeLabel",
    titleKey: "chat:feedbackNegativeTitle",
    Icon: ThumbsDown,
  },
} satisfies Record<MessageFeedbackRating, { labelKey: string; titleKey: string; Icon: typeof ThumbsUp }>;

function FeedbackAction({ rating, currentFeedback, onSubmit }: FeedbackActionProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [savedTime, setSavedTime] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const config = feedbackConfig[rating];
  const label = t(config.labelKey);
  const isSelected = currentFeedback?.rating === rating;
  const Icon = config.Icon;

  useEffect(() => {
    if (!open) return;

    if (currentFeedback?.rating === rating) {
      setSavedTime(currentFeedback.saved_time);
      setComment(currentFeedback.comment ?? "");
      return;
    }

    setSavedTime(null);
    setComment("");
  }, [currentFeedback, open, rating]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);

    try {
      await onSubmit({
        rating,
        savedTime: rating === "positive" ? savedTime : null,
        comment: comment.trim() || null,
      });
      setOpen(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className={cn(
            "p-1 rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-muted transition-colors",
            isSelected && "text-foreground",
          )}
          aria-label={label}
          aria-pressed={isSelected}
          title={label}
        >
          <Icon className="h-4 w-4" fill={isSelected ? "currentColor" : "none"} />
        </button>
      </DialogTrigger>
      <DialogContent className="max-w-[420px] gap-4 rounded-xl p-6">
        <form className="space-y-4" onSubmit={handleSubmit}>
          <DialogTitle className="pr-8 text-xl font-semibold leading-tight">
            {t(config.titleKey)}
          </DialogTitle>
          {rating === "positive" ? (
            <PositiveFeedbackFields
              savedTime={savedTime}
              onSavedTimeChange={setSavedTime}
              comment={comment}
              onCommentChange={setComment}
            />
          ) : (
            <NegativeFeedbackFields comment={comment} onCommentChange={setComment} />
          )}
          <div className="flex items-center justify-end gap-3 pt-1">
            <DialogClose asChild>
              <Button type="button" variant="ghost" className="px-5">
                {t("common:cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" className="rounded-xl px-5" disabled={isSubmitting}>
              {isSubmitting ? t("chat:feedbackSubmitting") : t("chat:feedbackSubmit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const savedTimeOptions = [
  { value: "up_to_15_min", labelKey: "chat:feedbackSavedTime15Min" },
  { value: "up_to_30_min", labelKey: "chat:feedbackSavedTime30Min" },
  { value: "up_to_1h", labelKey: "chat:feedbackSavedTime1Hour" },
  { value: "up_to_2h", labelKey: "chat:feedbackSavedTime2Hours" },
  { value: "up_to_3h", labelKey: "chat:feedbackSavedTime3Hours" },
  { value: "over_3h", labelKey: "chat:feedbackSavedTimeOver3Hours" },
];

interface PositiveFeedbackFieldsProps {
  savedTime: string | null;
  onSavedTimeChange: (value: string) => void;
  comment: string;
  onCommentChange: (value: string) => void;
}

function PositiveFeedbackFields({
  savedTime,
  onSavedTimeChange,
  comment,
  onCommentChange,
}: PositiveFeedbackFieldsProps) {
  const { t } = useTranslation();

  return (
    <>
      <div className="grid grid-cols-2 gap-2.5">
        {savedTimeOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onSavedTimeChange(option.value)}
            className={cn(
              "rounded-lg border border-input bg-background px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              savedTime === option.value && "border-foreground text-foreground",
            )}
          >
            {t(option.labelKey)}
          </button>
        ))}
      </div>
      <textarea
        value={comment}
        onChange={(event) => onCommentChange(event.target.value)}
        placeholder={t("chat:feedbackPositiveCommentPlaceholder")}
        rows={4}
        className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
      />
    </>
  );
}

interface NegativeFeedbackFieldsProps {
  comment: string;
  onCommentChange: (value: string) => void;
}

function NegativeFeedbackFields({ comment, onCommentChange }: NegativeFeedbackFieldsProps) {
  const { t } = useTranslation();

  return (
    <textarea
      value={comment}
      onChange={(event) => onCommentChange(event.target.value)}
      placeholder={t("chat:feedbackNegativeCommentPlaceholder")}
      rows={5}
      className="w-full resize-none rounded-xl border border-foreground bg-background px-4 py-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
    />
  );
}

interface MessageFeedbackProps {
  chatId?: string | null;
  messageId?: string;
  initialFeedback?: ChatMessageFeedbackResponse | null;
  onFeedbackSaved?: (feedback: ChatMessageFeedbackResponse) => void;
}

export function MessageFeedback({
  chatId = null,
  messageId,
  initialFeedback = null,
  onFeedbackSaved,
}: MessageFeedbackProps) {
  const { t } = useTranslation();
  const [currentFeedback, setCurrentFeedback] = useState<ChatMessageFeedbackResponse | null>(
    initialFeedback,
  );

  useEffect(() => {
    setCurrentFeedback(initialFeedback);
  }, [initialFeedback]);

  const handleSubmit = async ({ rating, savedTime, comment }: MessageFeedbackPayload) => {
    if (!chatId || !messageId) {
      sonnerToast.error(t("chat:feedbackMissingMessageError"));
      throw new Error("Missing chat or message id for feedback submission");
    }

    try {
      const feedback = await createMessageFeedback(
        chatId,
        messageId,
        toCreateMessageFeedbackRequest({ rating, savedTime, comment }),
      );
      setCurrentFeedback(feedback);
      onFeedbackSaved?.(feedback);
    } catch (error) {
      console.error("[MessageFeedback] Failed to save message feedback:", error);
      sonnerToast.error(t("chat:feedbackSaveError"));
      throw error;
    }
  };

  return (
    <div className="flex items-center gap-1" aria-label={t("chat:feedbackGroupLabel")}>
      <FeedbackAction
        rating="positive"
        currentFeedback={currentFeedback}
        onSubmit={handleSubmit}
      />
      <FeedbackAction
        rating="negative"
        currentFeedback={currentFeedback}
        onSubmit={handleSubmit}
      />
    </div>
  );
}
