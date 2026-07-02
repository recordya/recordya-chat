import { useState, useEffect, useCallback } from "react";
import { useAuth } from "./useAuth";
import { getNextChatIdAfterDelete } from "./useChatSelection";
import { Message, ToolResultRecord } from "@/components/ChatMessage";
import type { ReasoningStep } from "@/hooks/useAgentStream";
import {
  listChats,
  createChat,
  updateChat as apiUpdateChat,
  deleteChat as apiDeleteChat,
  listMessages,
  createMessage,
  searchChats as apiSearchChats,
  type ChatResponse,
  type ChatMessageResponse,
  type CreateMessageRequest,
} from "@/lib/api";

export interface Chat {
  id: string;
  title: string;
  datasource: string | null;
  created_at: string;
  updated_at: string;
  user_id?: string;
}

// Convert API message response to internal Message shape, including tool history.
export function apiMessageToMessage(m: ChatMessageResponse): Message {
  return {
    id: m.id,
    role: m.role as "user" | "assistant",
    content: m.content,
    isPersisted: true,
    sql: m.sql_query || undefined,
    sqlMode: undefined,
    queryResults: m.results_json ? JSON.parse(m.results_json) : undefined,
    toolResults: (m.tool_results as unknown as ToolResultRecord[]) || undefined,
    reasoningSteps: (m.reasoning_steps as unknown as ReasoningStep[]) || undefined,
    langfuseTraceId: m.langfuse_trace_id ?? undefined,
    feedback: m.feedback ?? undefined,
  };
}

// Build a create-message API payload from an internal Message plus optional SQL artifacts.
export function messageToCreateRequest(
  message: Message,
  sqlQuery?: string,
  results?: unknown[]
): CreateMessageRequest {
  return {
    role: message.role,
    content: message.content,
    sql_query: sqlQuery || null,
    results_json: results ? JSON.stringify(results) : null,
    tool_results: message.toolResults
      ? (message.toolResults as unknown as Record<string, unknown>[])
      : null,
    reasoning_steps: message.reasoningSteps
      ? (message.reasoningSteps as unknown as Record<string, unknown>[])
      : null,
    langfuse_trace_id: message.langfuseTraceId ?? null,
  };
}

export function useChatHistory() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatsLoaded, setChatsLoaded] = useState(false);
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();

  // Convert API response to internal Chat type
  const toChat = (response: ChatResponse): Chat => ({
    id: response.id,
    title: response.title || "Nowy czat",
    datasource: response.datasource ?? null,
    created_at: response.created_at,
    updated_at: response.updated_at,
  });

  // Fetch all chats for current user
  const fetchChats = useCallback(async () => {
    if (!isAuthenticated) return;

    try {
      const data = await listChats();
      setChats(data.map(toChat));
    } catch (error) {
      console.error("Error fetching chats:", error);
    } finally {
      setChatsLoaded(true);
    }
  }, [isAuthenticated]);

  // Load messages for a chat
  const loadChat = useCallback(async (chatId: string) => {
    setIsLoading(true);
    try {
      const data = await listMessages(chatId);

      setMessages(data.map(apiMessageToMessage));

      setCurrentChatId(chatId);
    } catch (error) {
      console.error("Error loading chat:", error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Create new chat (does NOT reset messages - caller manages state)
  const createNewChat = useCallback(async (datasource?: string | null) => {
    if (!isAuthenticated) return null;

    try {
      const data = await createChat({ title: "Nowy czat", datasource: datasource ?? null });
      const chat = toChat(data);
      setChats(prev => [chat, ...prev]);
      setCurrentChatId(chat.id);
      return chat.id;
    } catch (error) {
      console.error("Error creating chat:", error);
      return null;
    }
  }, [isAuthenticated]);

  // Start new chat (clear current)
  const startNewChat = useCallback(() => {
    setCurrentChatId(null);
    setMessages([]);
  }, []);

  // Save message
  const saveMessage = useCallback(async (
    chatId: string,
    message: Message,
    sqlQuery?: string,
    results?: unknown[],
    sqlMode?: "predefined" | "dynamic"
  ): Promise<Message | undefined> => {
    if (!isAuthenticated) return undefined;
    void sqlMode;

    try {
      const savedMessage = await createMessage(
        chatId,
        messageToCreateRequest(message, sqlQuery, results)
      );
      return apiMessageToMessage(savedMessage);
    } catch (error) {
      console.error("Error saving message:", error);
      return undefined;
    }
  }, [isAuthenticated]);

  // Update chat title from first message
  const updateChatTitle = useCallback(async (chatId: string, firstMessage: string) => {
    const title = firstMessage.slice(0, 50) + (firstMessage.length > 50 ? "..." : "");
    
    try {
      await apiUpdateChat(chatId, { title });
      setChats(prev => prev.map(c => c.id === chatId ? { ...c, title } : c));
    } catch (error) {
      console.error("Error updating chat title:", error);
    }
  }, []);

  // Delete chat. Returns the id of the next chat to focus (caller decides
  // routing). Returns null when nothing remains below or above.
  const deleteChatFn = useCallback(async (chatId: string): Promise<string | null> => {
    try {
      await apiDeleteChat(chatId);
      const nextChatId = getNextChatIdAfterDelete(chats, chatId);
      setChats(prev => prev.filter(c => c.id !== chatId));
      return nextChatId;
    } catch (error) {
      console.error("Error deleting chat:", error);
      return null;
    }
  }, [chats]);

  // Search chats
  const searchChatsFn = useCallback(async (query: string) => {
    if (!isAuthenticated) return;
    
    if (!query.trim()) {
      fetchChats();
      return;
    }
    
    try {
      const data = await apiSearchChats(query);
      setChats(data.map(toChat));
    } catch (error) {
      console.error("Error searching chats:", error);
    }
  }, [fetchChats, isAuthenticated]);

  // Fetch chats when authenticated
  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      fetchChats();
    }
  }, [fetchChats, isAuthenticated, authLoading]);

  return {
    chats,
    chatsLoaded,
    currentChatId,
    messages,
    setMessages,
    isLoading,
    loadChat,
    createNewChat,
    startNewChat,
    saveMessage,
    updateChatTitle,
    deleteChat: deleteChatFn,
    searchChats: searchChatsFn,
    fetchChats
  };
}
