import { memo } from "react";
import { useTranslation } from "react-i18next";
import { User, RotateCcw } from "lucide-react";
import { parseSelectFieldMeta } from "@/utils/sqlParser";
import { MessageContent } from "./MessageContent";
import { ReasoningPanel } from "./ReasoningPanel";
import { Slot } from "./Slot";
import { MessageFeedback } from "./MessageFeedback";
import type { ReasoningStep } from "@/hooks/useAgentStream";
import type { ChatMessageFeedbackResponse } from "@/lib/api";
import { useUserRole } from "@/hooks/useUserRole";
import {
  resultRegistry,
  widgetRegistry,
  extractWidgetDescriptor,
  DefaultResultsTableWidget,
  formatConfigRegistry,
  FormatConfigProvider,
} from "@/plugins/registry";

const WIDGET_MAKE_CHOICES_MARKER = "WIDGET_MAKE_CHOICES_ANSWERS";

function getUserVisibleContent(content: string): string {
  const markerIndex = content.indexOf(WIDGET_MAKE_CHOICES_MARKER);
  if (markerIndex === -1) {
    return content;
  }
  return content.slice(0, markerIndex).trimEnd();
}

export interface ToolResultRecord {
  tool: string;
  tool_name?: string;
  tool_call_id?: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  duration_ms?: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isPersisted?: boolean;
  sourcePluginId?: string;
  sql?: string;
  sqlMode?: "predefined" | "dynamic";
  queryResults?: Record<string, unknown>[];
  toolResults?: ToolResultRecord[];
  reasoningSteps?: ReasoningStep[];
  langfuseTraceId?: string;
  feedback?: ChatMessageFeedbackResponse;
}

interface ChatMessageProps {
  message: Message;
  agentId?: string;
  onSubmitUserMessage?: (text: string) => void;
  onSetComposerText?: (text: string) => void;
  chatId?: string | null;
  showFeedbackActions?: boolean;
  showRetryAction?: boolean;
  onRetryResponse?: () => void;
  onFeedbackSaved?: (messageId: string, feedback: ChatMessageFeedbackResponse) => void;
}


export const ChatMessage = memo(function ChatMessage({
  message,
  agentId,
  onSubmitUserMessage,
  onSetComposerText,
  chatId,
  showFeedbackActions = false,
  showRetryAction = false,
  onRetryResponse,
  onFeedbackSaved,
}: ChatMessageProps) {
  const { isSuperAdmin } = useUserRole();
  const { t } = useTranslation();
  const isUser = message.role === "user";

  if (isUser) {
    const visibleUserContent = getUserVisibleContent(message.content);
    return (
      <div className="flex gap-3 justify-end">
        <div className="max-w-[85%] rounded-2xl px-4 py-3 bg-muted text-foreground">
          <p className="text-sm whitespace-pre-wrap">{visibleUserContent}</p>
        </div>
        <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center flex-shrink-0">
          <User className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>
    );
  }

  const hasResults = Array.isArray(message.queryResults) && message.queryResults.length > 0;

  const sourcePluginId = message.sourcePluginId ?? agentId;
  const formatConfig = formatConfigRegistry.get(sourcePluginId);

  const sqlFieldMeta = message.sql
    ? parseSelectFieldMeta(message.sql, { durationColumns: formatConfig.durationColumnNames })
    : [];
  const sqlFields = sqlFieldMeta.map((f) => f.key);
  const durationFields = sqlFieldMeta
    .filter((f) => f.usesDurationColumn)
    .map((f) => f.key);
  const resultDecision = hasResults
    ? resultRegistry.resolve({
        agentId,
        sourcePluginId,
        messageId: message.id,
        content: message.content,
        sql: message.sql,
        sqlMode: message.sqlMode,
        queryResults: message.queryResults!,
        fields: sqlFields,
        durationFields,
        submitUserMessage: onSubmitUserMessage,
        setComposerText: onSetComposerText,
      })
    : null;
  const widgetDescriptor = hasResults
    ? extractWidgetDescriptor(message.queryResults!)
    : null;
  const widgetDecision =
    hasResults &&
    resultDecision?.action === "default" &&
    widgetDescriptor
      ? widgetRegistry.resolve(
          {
            agentId,
            sourcePluginId,
            messageId: message.id,
            content: message.content,
            sql: message.sql,
            sqlMode: message.sqlMode,
            queryResults: message.queryResults!,
            fields: sqlFields,
            durationFields,
            submitUserMessage: onSubmitUserMessage,
            setComposerText: onSetComposerText,
          },
          widgetDescriptor
        )
      : null;
  const slotContext = {
    agentId,
    messageId: message.id,
    message,
    sourcePluginId,
    submitUserMessage: onSubmitUserMessage,
    setComposerText: onSetComposerText,
  };

  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center flex-shrink-0">
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/>
        </svg>
      </div>
      
      <div className="flex-1 min-w-0 space-y-3">
        {isSuperAdmin && message.reasoningSteps && message.reasoningSteps.length > 0 && (
          <ReasoningPanel
            steps={message.reasoningSteps}
            agentId={agentId}
            sourcePluginId={sourcePluginId}
          />
        )}

        <MessageContent
          content={message.content}
          messageId={message.id}
          agentId={agentId}
          sourcePluginId={sourcePluginId}
          hasResults={hasResults}
        />

        <Slot name="chat.message.content" context={slotContext} />

        <FormatConfigProvider value={formatConfig}>
          {hasResults && resultDecision?.action === "render" && resultDecision.node}
          {hasResults && resultDecision?.action === "default" && widgetDecision?.action === "render" && widgetDecision.node}
          {hasResults &&
            resultDecision?.action === "default" &&
            (!widgetDecision || widgetDecision.action === "default") && (
            <DefaultResultsTableWidget
              context={{
                agentId,
                sourcePluginId,
                messageId: message.id,
                content: message.content,
                sql: message.sql,
                sqlMode: message.sqlMode,
                queryResults: message.queryResults!,
                fields: sqlFields,
                durationFields,
                submitUserMessage: onSubmitUserMessage,
                setComposerText: onSetComposerText,
              }}
            />
            )}
        </FormatConfigProvider>

        <Slot name="chat.message.actions" context={slotContext} />

        {(showFeedbackActions || showRetryAction) && (
          <div className="flex items-center gap-1 pt-1">
            {showRetryAction && onRetryResponse && (
              <button
                onClick={onRetryResponse}
                className="p-1 rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-muted transition-colors"
                title={t("chat:retry")}
                type="button"
              >
                <RotateCcw className="h-4 w-4" />
              </button>
            )}
            {showFeedbackActions && (
              <MessageFeedback
                chatId={chatId ?? null}
                messageId={message.id}
                initialFeedback={message.feedback ?? null}
                onFeedbackSaved={(feedback) => onFeedbackSaved?.(message.id, feedback)}
              />
            )}
          </div>
        )}

      </div>
    </div>
  );
});
