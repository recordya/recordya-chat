import { useState, useEffect, useCallback } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ChatInterface } from "@/components/ChatInterface";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { IconRail, CHAT_VIEW_ID } from "@/components/IconRail";
import { SidebarProvider } from "@/components/ui/sidebar";
import { useChatHistory } from "@/hooks/use-chat-history";
import { useUserRole } from "@/hooks/useUserRole";
import { listDataSources, type DataSourceInfo } from "@/lib/api";
import { viewRegistry } from "@/plugins/ViewRegistry";
import { filterNavItemsForRole } from "@/plugins/navAccess";
import { resolveChatRouteAction } from "./chatRouteSync";
import { resolveSelectedAgent } from "./agentSelection";

/** Resolve current URL pathname to an activeView id (registry id or CHAT_VIEW_ID). */
function resolveActiveView(pathname: string): string {
  if (pathname === "/" || pathname.startsWith("/c/")) return CHAT_VIEW_ID;
  const nav = viewRegistry.getNavItems().find((n) => n.path === pathname);
  return nav ? nav.id : CHAT_VIEW_ID;
}

const SELECTED_AGENT_STORAGE_KEY = "recordya:selected-agent";

function readStoredAgent(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SELECTED_AGENT_STORAGE_KEY);
}

const Index = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { chatId: urlChatId } = useParams<{ chatId?: string }>();

  const {
    chats,
    chatsLoaded,
    currentChatId,
    messages,
    setMessages,
    loadChat,
    createNewChat,
    startNewChat,
    saveMessage,
    updateChatTitle,
    deleteChat,
    searchChats,
  } = useChatHistory();

  const [input, setInput] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [agents, setAgents] = useState<DataSourceInfo[]>([]);
  const [agentsLoaded, setAgentsLoaded] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(readStoredAgent);

  // Derive activeView from current URL
  const activeView = resolveActiveView(location.pathname);

  const handleViewSelect = useCallback(
    (id: string) => {
      if (id === CHAT_VIEW_ID) {
        navigate("/");
      } else {
        const nav = viewRegistry.getNavItems().find((n) => n.id === id);
        if (nav) navigate(nav.path);
      }
    },
    [navigate],
  );

  // Fetch agents on mount
  useEffect(() => {
    listDataSources()
      .then((data) => {
        setAgents(data.datasources);
      })
      .catch(() => {
        setAgents([]);
      })
      .finally(() => {
        setAgentsLoaded(true);
      });
  }, []);

  // URL is the source of truth for the active chat. When :chatId changes,
  // load that chat; when it disappears (route "/"), clear current chat.
  // resolveChatRouteAction encodes the full decision table (see tests).
  useEffect(() => {
    const action = resolveChatRouteAction({
      urlChatId,
      currentChatId,
      chatsLoaded,
      knownChatIds: new Set(chats.map((c) => c.id)),
    });
    if (action.kind === "load") loadChat(action.chatId);
    else if (action.kind === "redirect-home") navigate("/", { replace: true });
    else if (action.kind === "start-new") startNewChat();
  }, [urlChatId, currentChatId, chats, chatsLoaded, loadChat, startNewChat, navigate]);

  // Resolve selected agent: a chat's datasource is authoritative only when the
  // URL points to that chat; otherwise the cached/explicit choice wins, falling
  // back to the first available plugin. See resolveSelectedAgent for the table.
  useEffect(() => {
    const action = resolveSelectedAgent({
      agentsLoaded,
      chatsLoaded,
      urlChatId,
      currentChatId,
      selectedAgent,
      availableAgents: agents.map((a) => a.name),
      currentChatDatasource:
        currentChatId !== null
          ? chats.find((c) => c.id === currentChatId)?.datasource ?? null
          : null,
    });
    if (action.kind === "select") setSelectedAgent(action.agent);
  }, [agents, agentsLoaded, chatsLoaded, chats, currentChatId, selectedAgent, urlChatId]);

  // Persist the agent choice so it survives a page refresh even when no
  // chat is open (e.g. just after clicking an agent in the sidebar).
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (selectedAgent) {
      window.localStorage.setItem(SELECTED_AGENT_STORAGE_KEY, selectedAgent);
    } else {
      window.localStorage.removeItem(SELECTED_AGENT_STORAGE_KEY);
    }
  }, [selectedAgent]);

  const handleSelectChat = useCallback(
    (chatId: string) => {
      navigate(`/c/${chatId}`);
    },
    [navigate],
  );

  const handleNewChat = useCallback(() => {
    setInput("");
    navigate("/");
  }, [navigate]);

  const handleSelectAgent = useCallback(
    (agentId: string) => {
      setSelectedAgent(agentId);
      setInput("");
      navigate("/");
    },
    [navigate],
  );

  const handleDeleteChat = useCallback(
    async (chatId: string) => {
      const nextChatId = await deleteChat(chatId);
      if (currentChatId === chatId) {
        navigate(nextChatId ? `/c/${nextChatId}` : "/", { replace: true });
      }
    },
    [currentChatId, deleteChat, navigate],
  );

  const createChatWithSelectedAgent = useCallback(async () => {
    const newId = await createNewChat(selectedAgent);
    if (newId) navigate(`/c/${newId}`, { replace: true });
    return newId;
  }, [createNewChat, navigate, selectedAgent]);

  const { role } = useUserRole();

  const selectedAgentData = agents.find((a) => a.name === selectedAgent);
  const pluginNavItems = filterNavItemsForRole(viewRegistry.getNavItems(), role);
  const isChatView = activeView === CHAT_VIEW_ID;
  const isAllowedOnCurrentPath =
    isChatView || pluginNavItems.some((item) => item.path === location.pathname);

  // Redirect away from plugin routes the current role cannot access
  useEffect(() => {
    if (role !== null && !isAllowedOnCurrentPath) {
      navigate("/", { replace: true });
    }
  }, [role, isAllowedOnCurrentPath, navigate]);

  return (
    <div className="h-dvh flex w-full overflow-hidden">
      {/* Icon rail — always visible, 80px wide */}
      <IconRail
        activeId={activeView}
        pluginNavItems={pluginNavItems}
        onSelect={handleViewSelect}
      />

      {isChatView ? (
        /* Chat view: sidebar + chat interface.
           --rail-width offsets the fixed-positioned Sidebar so it doesn't overlap the IconRail. */
        <SidebarProvider
          className="flex-1 min-w-0 !w-auto"
          style={{ "--rail-width": "5rem" } as React.CSSProperties}
        >
          <ChatSidebar
            chats={chats}
            currentChatId={currentChatId}
            agents={agents}
            agentsLoaded={agentsLoaded}
            selectedAgent={selectedAgent}
            onSelectChat={handleSelectChat}
            onNewChat={handleNewChat}
            onDeleteChat={handleDeleteChat}
            onRenameChat={updateChatTitle}
            onSearch={searchChats}
            onSelectAgent={handleSelectAgent}
          />

          <main className="flex-1 relative min-w-0 overflow-hidden">
            <ChatInterface
              messages={messages}
              setMessages={setMessages}
              currentChatId={currentChatId}
              onCreateChat={createChatWithSelectedAgent}
              onSaveMessage={saveMessage}
              onUpdateTitle={updateChatTitle}
              input={input}
              setInput={setInput}
              isProcessing={isProcessing}
              setIsProcessing={setIsProcessing}
              agentData={selectedAgentData}
              selectedAgent={selectedAgent}
            />
          </main>
        </SidebarProvider>
      ) : (
        /* Plugin view: full-width, no chat sidebar */
        <main className="flex-1 min-w-0 overflow-auto">
          {viewRegistry.getViewElement(activeView)}
        </main>
      )}
    </div>
  );
};

export default Index;
