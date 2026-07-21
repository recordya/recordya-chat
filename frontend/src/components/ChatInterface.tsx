import { useRef, useEffect, useState, useCallback, useMemo, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { ArrowUp, ArrowDown, Plus, Loader2, TrendingUp, BarChart, Mic, Sparkles, PanelLeft, Square, FileText } from "lucide-react";
import { useComposerMention } from "@/hooks/useComposerMention";
import { ChatMessage, Message, ToolResultRecord } from "./ChatMessage";
import { ReasoningPanel } from "./ReasoningPanel";
import { Slot } from "./Slot";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import { useUserRole } from "@/hooks/useUserRole";
import { useAgentStream } from "@/hooks/useAgentStream";
import { useModelSettings } from "@/contexts/ModelSettingsContext";
import { useSidebar, SidebarTrigger } from "@/components/ui/sidebar";
import { toast as sonnerToast } from "sonner";
import recordyaLogo from "@/assets/recordya-logo.png";
import { getShowBranding } from "@/lib/config";
import { extractFromToolHistory } from "@/utils/toolHistory";
import { shouldUpdateMessages, shouldShowProcessing, computeRetryAction } from "@/utils/chatIsolation";
import { mergeMessage, removeMessage, upsertMessage } from "@/utils/streamingMessages";
import { isScrolledToBottom } from "@/utils/scroll";
import { deleteLastMessages, type ChatMessageFeedbackResponse, type DataSourceInfo } from "@/lib/api";
import {
  referenceSuggestionRegistry,
  extractWidgetDescriptor,
} from "@/plugins/registry";
import {
  addReference,
  referenceKey,
  appendReferenceToken,
  filterReferencesInText,
  composeQuestionWithReferences,
  type ComposerReference,
} from "@/utils/composerReferences";
import { ComposerInput } from "./ComposerInput";

// Match backend validation constraint
const QUESTION_MAX_LENGTH = 4000;

// Map of Lucide icon names to components (for suggestion cards)
const iconMap: Record<string, React.ElementType> = {
  "trending-up": TrendingUp,
  "bar-chart": BarChart,
  mic: Mic,
  sparkles: Sparkles,
};



interface ChatInterfaceProps {
  messages: Message[];
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  currentChatId: string | null;
  onCreateChat: () => Promise<string | null>;
  onSaveMessage: (
    chatId: string,
    message: Message,
    sql?: string,
    results?: Record<string, unknown>[],
    sqlMode?: "predefined" | "dynamic"
  ) => Promise<Message | undefined>;
  onUpdateTitle: (chatId: string, title: string) => Promise<void>;
  input: string;
  setInput: (value: string) => void;
  isProcessing: boolean;
  setIsProcessing: (value: boolean) => void;
  agentData?: DataSourceInfo;
  selectedAgent?: string | null;
}

export function ChatInterface({
  messages,
  setMessages,
  currentChatId,
  onCreateChat,
  onSaveMessage,
  onUpdateTitle,
  input,
  setInput,
  isProcessing,
  setIsProcessing,
  agentData,
  selectedAgent,
}: ChatInterfaceProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const { t } = useTranslation();
  const { toast } = useToast();
  const { state: sidebarState } = useSidebar();
  const { remainingQueries, checkAndIncrementUsage, isLoading: roleLoading, isSuperAdmin } = useUserRole();
  const { selectedModel } = useModelSettings();
  const {
    status: streamStatus,
    steps: streamSteps,
    streamedContent,
    result: streamResult,
    error: streamError,
    runQuery: runStreamQuery,
    isStreaming,
    abort: abortStream,
    reset: resetStream,
  } = useAgentStream();

  // Always-fresh ref to the currently displayed chat ID.
  // Used to prevent streaming responses from leaking into a different chat
  // when the user switches chats while a request is still pending.
  const currentChatIdRef = useRef(currentChatId);
  currentChatIdRef.current = currentChatId;

  // Track which chat ID has an in-flight request so the loading spinner
  // is only shown when the user is viewing that specific chat.
  const [processingChatId, setProcessingChatId] = useState<string | null>(null);
  // Structured references ("chips") attached to the next user message,
  // independent of the typed text. Serialized into the question on submit.
  const [composerReferences, setComposerReferences] = useState<ComposerReference[]>([]);
  const [streamingAssistantMessageId, setStreamingAssistantMessageId] = useState<string | null>(null);
  const streamingAssistantMessageIdRef = useRef<string | null>(null);
  const showProcessingIndicator = shouldShowProcessing(isProcessing, processingChatId, currentChatId);
  const renderProcessingIndicator = showProcessingIndicator && !streamedContent;

  // Get suggestions from agent manifest
  const welcomeData = agentData?.welcome;
  const suggestions = welcomeData?.suggestions || [];

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: "smooth"
      });
    }
  }, []);

  useEffect(() => {
    setTimeout(scrollToBottom, 50);
  }, [messages, scrollToBottom]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const handleScroll = () => {
      const atBottom = isScrolledToBottom(container);
      isAtBottomRef.current = atBottom;
      setShowScrollButton(!atBottom);
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  // Keep the view glued to the bottom while content streams in. The DOM grows
  // without firing a scroll event, so follow the content when the user is
  // already at the bottom, otherwise reveal the "scroll to bottom" button.
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    if (isAtBottomRef.current) {
      container.scrollTop = container.scrollHeight;
    } else {
      setShowScrollButton(true);
    }
  }, [streamedContent, streamSteps, showProcessingIndicator]);

  useEffect(() => {
    if (!streamingAssistantMessageId || !streamedContent) return;
    if (!processingChatId || !shouldUpdateMessages(currentChatId, processingChatId)) return;

    const streamingMessage: Message = {
      id: streamingAssistantMessageId,
      role: "assistant",
      content: streamedContent,
      sourcePluginId: selectedAgent ?? undefined,
      reasoningSteps: streamSteps.length > 0 ? streamSteps : undefined,
    };

    setMessages((prev) => mergeMessage(prev, streamingMessage));
  }, [
    currentChatId,
    processingChatId,
    selectedAgent,
    setMessages,
    streamSteps,
    streamedContent,
    streamingAssistantMessageId,
  ]);

  const submitUserMessage = useCallback(
    async (
      question: string,
      clearComposer = false,
      /** When true the user message already exists in UI + DB (retry flow). */
      skipUserMessage = false,
      /** Structured references serialized into the message on submit. */
      references: ComposerReference[] = [],
    ): Promise<void> => {
      const trimmedQuestion = question.trim();
      if (!trimmedQuestion || isProcessing || roleLoading) {
        return;
      }

      // Check usage limit for non-admins
      const usageResult = await checkAndIncrementUsage();
      if (!usageResult.allowed) {
        sonnerToast.error(t("chat:limitReached", { limit: usageResult.limit }), {
          description: t("chat:limitResetDescription"),
        });
        return;
      }

      const userMessage: Message = {
        id: Date.now().toString(),
        role: "user",
        content: composeQuestionWithReferences(trimmedQuestion, references),
      };
      const sourcePluginId = selectedAgent ?? undefined;

      if (!skipUserMessage) {
        setMessages((prev) => [...prev, userMessage]);
      }
      if (clearComposer) {
        setInput("");
        setComposerReferences([]);
      }
      setIsProcessing(true);
      const assistantMessageId = `${Date.now() + 1}-assistant`;
      streamingAssistantMessageIdRef.current = assistantMessageId;
      setStreamingAssistantMessageId(assistantMessageId);
      // Clear any leftover reasoning/answer from the previous turn before the
      // async setup below, so the processing indicator can't briefly show stale
      // state from the previous chat while the next stream is being prepared.
      resetStream();

      try {
        // Create chat if needed
        let chatId = currentChatId;
        const isFirstMessage = messages.length === 0;

        if (!chatId) {
          chatId = await onCreateChat();
          if (!chatId) {
            throw new Error(t("chat:createChatError"));
          }
        }

        // Remember which chat owns this request (for spinner visibility)
        setProcessingChatId(chatId);

        // Save user message (skip on retry — it's already persisted)
        if (!skipUserMessage) {
          await onSaveMessage(chatId, userMessage);
        }

        // Update title with first message (visible text only, no machine payload)
        if (isFirstMessage) {
          await onUpdateTitle(chatId, trimmedQuestion);
        }

        // Helper: check if the user is still viewing the chat that started this request.
        // If they switched to another chat, we must not touch the UI messages state
        // (the response is still persisted to DB via onSaveMessage).
        const isStillActiveChat = () =>
          shouldUpdateMessages(currentChatIdRef.current, chatId);

        const saveAndReplaceAssistantMessage = async (
          message: Message,
          sqlQuery?: string,
          results?: Record<string, unknown>[],
          sqlMode?: "predefined" | "dynamic",
        ) => {
          const savedMessage = await onSaveMessage(chatId, message, sqlQuery, results, sqlMode);
          if (savedMessage && isStillActiveChat()) {
            setMessages((prev) =>
              prev.map((currentMessage) =>
                currentMessage.id === message.id
                  ? {
                      ...savedMessage,
                      sourcePluginId: message.sourcePluginId ?? savedMessage.sourcePluginId,
                    }
                  : currentMessage
              )
            );
          }
        };

        // Use streaming API for real-time status updates
        // Note: question is passed separately, so don't include userMessage in history
        const { result, error: queryError, httpStatus, steps: querySteps, aborted, partialContent } = await runStreamQuery({
          question: userMessage.content,
          conversationHistory: messages.map((message) => {
            const entry: {
              role: string;
              content: string;
              queryResults?: Record<string, unknown>[];
              toolResults?: Record<string, unknown>[];
            } = {
              role: message.role,
              content: message.content,
            };
            if (message.role === "assistant") {
              if (message.queryResults) {
                entry.queryResults = message.queryResults;
              }
              if (message.toolResults && message.toolResults.length > 0) {
                entry.toolResults =
                  message.toolResults as unknown as Record<string, unknown>[];
              }
            }
            return entry;
          }),
          model: selectedModel || undefined,
          datasource: sourcePluginId,
          chat_id: chatId, // For Langfuse session grouping
        });

        if (!result) {
          if (aborted) {
            const trimmedPartial = partialContent.trim();
            if (!trimmedPartial) {
              const streamMessageId = streamingAssistantMessageIdRef.current;
              if (streamMessageId && isStillActiveChat()) {
                setMessages((prev) => removeMessage(prev, streamMessageId));
              }
              return;
            }
            const stoppedMessage: Message = {
              id: streamingAssistantMessageIdRef.current ?? (Date.now() + 1).toString(),
              role: "assistant",
              content: trimmedPartial,
              sourcePluginId,
              reasoningSteps: querySteps && querySteps.length > 0 ? querySteps : undefined,
            };
            if (isStillActiveChat()) {
              setMessages((prev) => upsertMessage(prev, stoppedMessage));
            }
            await saveAndReplaceAssistantMessage(stoppedMessage);
            return;
          }
          if (queryError) {
            console.error("[ChatInterface] Stream failed:", queryError);
          }
          const content = httpStatus === 403
            ? `🔒 ${queryError || t("errors:accessRestricted")}`
            : t("errors:generic");
          const errorMessage: Message = {
            id: streamingAssistantMessageIdRef.current ?? (Date.now() + 1).toString(),
            role: "assistant",
            content,
            sourcePluginId,
          };
          if (isStillActiveChat()) {
            setMessages((prev) => upsertMessage(prev, errorMessage));
          }
          await saveAndReplaceAssistantMessage(errorMessage);
          return;
        }

        if (result.error) {
          const errorMessage: Message = {
            id: streamingAssistantMessageIdRef.current ?? (Date.now() + 1).toString(),
            role: "assistant",
            content: result.error,
            sourcePluginId,
          };
          if (isStillActiveChat()) {
            setMessages((prev) => upsertMessage(prev, errorMessage));
          }
          await saveAndReplaceAssistantMessage(errorMessage);
          return;
        }

        // Extract SQL and data from tool history for display
        const { sql, mode, queryResults } = extractFromToolHistory(
          result.tool_history || []
        );

        // Preserve full tool history on the message so subsequent turns
        // can replay it as native LLM tool messages (see ConversationBuilder).
        const toolResults: ToolResultRecord[] = (result.tool_history || []).map(
          (entry) => ({
            tool: entry.tool,
            tool_name: entry.tool,
            tool_call_id: entry.tool_call_id,
            arguments: entry.arguments,
            result: entry.result,
            duration_ms: entry.duration_ms,
          })
        );

        // Build assistant message with agent's response and any query results
        const assistantMessage: Message = {
          id: streamingAssistantMessageIdRef.current ?? (Date.now() + 1).toString(),
          role: "assistant",
          content: result.content || t("chat:noAnswer"),
          sourcePluginId,
          sql: sql || undefined,
          sqlMode: mode || undefined,
          queryResults:
            queryResults && queryResults.length > 0 ? queryResults : undefined,
          toolResults: toolResults.length > 0 ? toolResults : undefined,
          reasoningSteps: querySteps && querySteps.length > 0 ? querySteps : undefined,
          langfuseTraceId: result.langfuse_trace_id ?? undefined,
        };

        if (isStillActiveChat()) {
          setMessages((prev) => upsertMessage(prev, assistantMessage));
        }
        await saveAndReplaceAssistantMessage(
          assistantMessage,
          sql || undefined,
          queryResults || undefined,
          mode || undefined
        );
      } catch {
        const streamMessageId = streamingAssistantMessageIdRef.current;
        if (streamMessageId) {
          setMessages((prev) => removeMessage(prev, streamMessageId));
        }
        toast({
          title: t("errors:title"),
          description: t("errors:unexpected"),
          variant: "destructive",
        });
      } finally {
        setProcessingChatId(null);
        streamingAssistantMessageIdRef.current = null;
        setStreamingAssistantMessageId(null);
        setIsProcessing(false);
      }
    },
    [
      checkAndIncrementUsage,
      currentChatId,
      isProcessing,
      messages,
      selectedModel,
      onCreateChat,
      onSaveMessage,
      onUpdateTitle,
      resetStream,
      roleLoading,
      runStreamQuery,
      selectedAgent,
      setInput,
      setIsProcessing,
      setMessages,
      t,
      toast,
    ]
  );

  const handleSubmitFromMessage = useCallback(
    (text: string) => {
      void submitUserMessage(text, false);
    },
    [submitUserMessage],
  );

  const handleSetComposerText = useCallback(
    (text: string) => setInput(text),
    [setInput],
  );

  // Registers the reference without touching the text — the mention flow
  // inserts its own inline token at the caret position.
  const registerComposerReference = useCallback(
    (reference: ComposerReference) => {
      setComposerReferences((prev) => addReference(prev, reference));
    },
    [],
  );

  // Used outside the mention flow (e.g. source card button): registers the
  // reference and appends its inline token to the composer text.
  const handleAddComposerReference = useCallback(
    (reference: ComposerReference) => {
      setComposerReferences((prev) => addReference(prev, reference));
      setInput(appendReferenceToken(input, reference));
    },
    [input, setInput],
  );

  // References already rendered in the conversation (e.g. on source cards),
  // newest first — surfaced as the first group of "@" mention suggestions.
  const conversationReferences = useMemo(() => {
    const seen = new Set<string>();
    const references: ComposerReference[] = [];
    for (let i = messages.length - 1; i >= 0; i--) {
      const message = messages[i];
      if (!Array.isArray(message.queryResults) || message.queryResults.length === 0) {
        continue;
      }
      const descriptor = extractWidgetDescriptor(message.queryResults);
      if (!descriptor) {
        continue;
      }
      const extracted = referenceSuggestionRegistry.extractConversationReferences(
        descriptor.widgetType,
        descriptor.payload,
      );
      for (const reference of extracted) {
        const key = referenceKey(reference);
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);
        references.push(reference);
      }
    }
    return references;
  }, [messages]);

  const composerMention = useComposerMention({
    input,
    setInput,
    addReference: registerComposerReference,
    conversationReferences,
  });

  // Reacts to headless provider mounts, so the placeholder only advertises
  // the "@" mention when the current agent actually supports it.
  const hasMentionProviders = useSyncExternalStore(
    referenceSuggestionRegistry.subscribe,
    () => referenceSuggestionRegistry.hasProviders(),
  );

  const handleRetry = useCallback(
    (errorMessageId: string) => {
      const action = computeRetryAction(messages, errorMessageId);
      if (!action) return;

      // Remove only the error message from UI — keep the user message intact
      setMessages((prev) => prev.filter((m) => m.id !== errorMessageId));

      // Delete only the error message from DB (last 1 message)
      if (currentChatId) {
        void deleteLastMessages(currentChatId, 1).catch((err) =>
          console.error("[ChatInterface] Failed to delete error message before retry:", err),
        );
      }

      // Re-submit with skipUserMessage=true so the existing user message
      // is neither duplicated in UI nor re-saved to DB
      void submitUserMessage(action.question, false, true);
    },
    [currentChatId, messages, setMessages, submitUserMessage],
  );

  const handleFeedbackSaved = useCallback(
    (messageId: string, feedback: ChatMessageFeedbackResponse) => {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === messageId ? { ...message, feedback } : message
        )
      );
    },
    [setMessages],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Only references whose inline token survived in the text are attached —
    // deleting "@[label]" from the composer detaches the reference.
    await submitUserMessage(
      input,
      true,
      false,
      filterReferencesInText(input, composerReferences),
    );
  };

  const chatSlotContext = {
    agentId: selectedAgent ?? undefined,
    currentChatId,
    messages,
    isProcessing,
    setComposerText: setInput,
    submitUserMessage: handleSubmitFromMessage,
    addComposerReference: handleAddComposerReference,
  };

  return (
    <div className="flex flex-col h-full overflow-hidden bg-background">
      <Slot name="detail.panel" context={chatSlotContext} />

      {/* Top header bar: sidebar toggle + agent name */}
      <div className="flex items-center gap-2 px-2 h-12 shrink-0 border-b border-border">
        <SidebarTrigger className="h-8 w-8 shrink-0 rounded-md hover:bg-muted">
          <PanelLeft className="h-4 w-4" />
        </SidebarTrigger>
        {agentData && (
          <span className="text-sm font-medium truncate">{agentData.display_name}</span>
        )}
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto pb-32"
      >
        {messages.length === 0 && !renderProcessingIndicator ? (
          <div className="h-full flex flex-col items-center justify-center px-4">
            <div className="max-w-2xl w-full text-center space-y-8">
              <div className="space-y-2">
                <h1 className="text-2xl font-semibold">
                  {welcomeData?.title || t("chat:welcomeTitle")}
                </h1>
                <p className="text-muted-foreground">
                  {welcomeData?.description || t("chat:welcomeDescription")}
                </p>
              </div>
              
              {suggestions.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left auto-rows-fr">
                  {suggestions.map((suggestion, i) => {
                    const IconComponent = iconMap[suggestion.icon || ""] || null;
                    return (
                      <button
                        key={i}
                        onClick={() => setInput(suggestion.text)}
                        className="p-3 rounded-xl border border-border hover:bg-muted transition-colors text-sm text-muted-foreground hover:text-foreground h-full flex items-center gap-3"
                      >
                        {IconComponent && (
                          <IconComponent className="h-4 w-4 flex-shrink-0" />
                        )}
                        <span>{suggestion.text}</span>
                      </button>
                    );
                  })}
                </div>
              )}

              <Slot name="chat.welcome" context={chatSlotContext} />
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto py-8 px-4 space-y-6">
            {messages.map((message, index) => {
              const isLastAssistant =
                message.role === "assistant" &&
                !messages.slice(index + 1).some((m) => m.role === "assistant");
              const isStreamingAssistantMessage =
                isProcessing && message.id === streamingAssistantMessageId;
              const showFeedbackActions =
                Boolean(currentChatId) &&
                message.role === "assistant" &&
                message.isPersisted === true &&
                !isStreamingAssistantMessage;
              const showRetryAction = isLastAssistant && !isProcessing;
              return (
                <ChatMessage
                  key={message.id}
                  message={message}
                  agentId={selectedAgent ?? undefined}
                  onSubmitUserMessage={handleSubmitFromMessage}
                  onSetComposerText={handleSetComposerText}
                  onAddComposerReference={handleAddComposerReference}
                  chatId={currentChatId}
                  showFeedbackActions={showFeedbackActions}
                  showRetryAction={showRetryAction}
                  onRetryResponse={() => handleRetry(message.id)}
                  onFeedbackSaved={handleFeedbackSaved}
                />
              );
            })}
            {renderProcessingIndicator && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center flex-shrink-0">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
                <div className="flex-1 min-w-0 space-y-2 pt-2">
                  {/* Hide the progress status once a final result exists (the
                      terminal "ready" state); aborted/error keep result null. */}
                  {!streamResult && (
                    <div className="text-muted-foreground text-sm">
                      {streamStatus}
                    </div>
                  )}
                  {isStreaming && isSuperAdmin && streamSteps.length > 0 && (
                    <ReasoningPanel
                      steps={streamSteps}
                      isStreaming
                      agentId={selectedAgent ?? undefined}
                      sourcePluginId={selectedAgent ?? undefined}
                    />
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className={cn(
        "fixed bottom-0 left-0 right-0 z-20 bg-background transition-[left] duration-200 ease-linear",
        sidebarState === "expanded"
          ? "md:left-[calc(var(--rail-width,0px)+var(--sidebar-width))]"
          : "md:left-[var(--rail-width,0px)]"
      )}>
        <div className="max-w-3xl mx-auto px-4 relative">
          {/* Scroll to bottom button */}
          <button
            onClick={scrollToBottom}
            className={cn(
              "absolute left-1/2 -translate-x-1/2 -top-12 h-8 w-8 rounded-full border border-border bg-background shadow-md flex items-center justify-center hover:bg-muted transition-all",
              showScrollButton ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4 pointer-events-none"
            )}
            aria-label={t("chat:scrollToBottom")}
          >
            <ArrowDown className="h-4 w-4 text-muted-foreground" />
          </button>

          <form onSubmit={handleSubmit} className="pb-3 pt-2">
            <Slot name="chat.input.before" context={chatSlotContext} />
            <div className="relative rounded-full border border-border bg-muted/30 shadow-sm focus-within:border-muted-foreground/50 focus-within:shadow-md transition-all pl-3 pr-2 py-1.5">
              {composerMention.mention && (
                <div
                  className="absolute bottom-full left-0 right-0 mb-2 rounded-xl border border-border bg-background shadow-lg overflow-hidden z-20"
                  role="listbox"
                  aria-label={t("chat:mentionSuggestionsLabel")}
                >
                  {composerMention.isLoading ? (
                    <div className="flex items-center gap-2 px-3 py-2.5 text-xs text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                      {t("chat:mentionLoading")}
                    </div>
                  ) : composerMention.suggestions.length === 0 ? (
                    <div className="px-3 py-2.5 text-xs text-muted-foreground">
                      {t("chat:mentionNoResults")}
                    </div>
                  ) : (
                    <ul className="max-h-64 overflow-y-auto py-1">
                      {composerMention.suggestions.map((suggestion, index) => (
                        <li
                          key={referenceKey(suggestion.reference)}
                          role="option"
                          aria-selected={index === composerMention.activeIndex}
                        >
                          {index === 0 && composerMention.conversationCount > 0 && (
                            <div className="px-3 pt-1.5 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                              {t("chat:mentionGroupConversation")}
                            </div>
                          )}
                          {index === composerMention.conversationCount &&
                            composerMention.conversationCount > 0 && (
                            <div className="mt-1 border-t border-border px-3 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                              {t("chat:mentionGroupAll")}
                            </div>
                          )}
                          <button
                            type="button"
                            onClick={() => composerMention.pick(suggestion)}
                            onMouseEnter={() => composerMention.setActiveIndex(index)}
                            className={cn(
                              "w-full flex items-center gap-2 px-3 py-2 text-left text-sm transition-colors",
                              index === composerMention.activeIndex
                                ? "bg-muted text-foreground"
                                : "text-foreground hover:bg-muted/60"
                            )}
                          >
                            <FileText className="h-4 w-4 flex-shrink-0 text-muted-foreground" aria-hidden />
                            <span className="truncate">{suggestion.reference.label}</span>
                            {suggestion.description && (
                              <span className="ml-auto flex-shrink-0 text-xs text-muted-foreground truncate max-w-[10rem]">
                                {suggestion.description}
                              </span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <div className="flex items-center gap-2">
                {/* Plus icon */}
                <button
                  type="button"
                  className="flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center text-muted-foreground hover:bg-muted transition-colors"
                  aria-label={t("chat:add")}
                >
                  <Plus className="h-5 w-5" />
                </button>

                {/* Input: contentEditable rendering reference tokens as chips.
                    Backspace on a chip removes it whole (atomic element). */}
                <ComposerInput
                  value={input}
                  references={composerReferences}
                  onChange={setInput}
                  onCaretUpdate={composerMention.updateFromPosition}
                  onBlur={() => setTimeout(composerMention.close, 150)}
                  placeholder={t(
                    hasMentionProviders
                      ? "chat:inputPlaceholderWithMention"
                      : "chat:inputPlaceholder"
                  )}
                  maxLength={QUESTION_MAX_LENGTH}
                  disabled={isProcessing}
                  onKeyDown={(e) => {
                    if (composerMention.handleKeyDown(e)) {
                      e.preventDefault();
                      return;
                    }
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSubmit(e);
                    }
                  }}
                />

                {/* Submit / stop button — stop only shows for the chat that owns the in-flight request */}
                {isStreaming && processingChatId !== null && processingChatId === currentChatId ? (
                  <button
                    type="button"
                    onClick={abortStream}
                    aria-label={t("chat:stop")}
                    className="flex-shrink-0 h-8 w-8 rounded-full bg-foreground text-background flex items-center justify-center hover:opacity-80 transition-opacity"
                  >
                    <Square className="h-3.5 w-3.5 fill-current" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim() || isProcessing}
                    aria-label={t("chat:send")}
                    className="flex-shrink-0 h-8 w-8 rounded-full bg-foreground text-background flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed hover:opacity-80 transition-opacity"
                  >
                    <ArrowUp className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>

            {getShowBranding() && (
              <div className="flex items-center justify-center gap-1.5 mt-2 h-5">
                <span className="text-xs text-muted-foreground/60">{t("common:poweredBy")}</span>
                <a
                  href="https://recordya.ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:opacity-80 transition-opacity"
                >
                  <img src={recordyaLogo} alt="Recordya" className="h-6" />
                </a>
              </div>
            )}
            <Slot name="chat.input.after" context={chatSlotContext} />
          </form>
        </div>
      </div>
    </div>
  );
}
