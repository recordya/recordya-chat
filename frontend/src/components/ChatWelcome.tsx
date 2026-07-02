/**
 * Chat welcome view that dispatches to plugin handlers.
 * 
 * Tries plugin-specific welcome first, falls back to default.
 */

import { useTranslation } from "react-i18next";
import { pluginEventBus, type PluginEvent, type WelcomeEventData } from "@/plugins/EventBus";

interface AgentManifest {
  welcome?: {
    title?: string;
    description?: string;
    suggestions?: Array<{
      text: string;
      icon?: string;
    }>;
  };
}

interface ChatWelcomeProps {
  agentId: string;
  manifest?: AgentManifest;
  suggestions?: string[];
  onSuggestionClick?: (text: string) => void;
}

interface DefaultWelcomeProps {
  title?: string;
  description?: string;
  suggestions?: string[];
  onSuggestionClick?: (text: string) => void;
}

function DefaultWelcome({
  title,
  description,
  suggestions = [],
  onSuggestionClick,
}: DefaultWelcomeProps) {
  const { t } = useTranslation();
  return (
    <div className="h-full flex flex-col items-center justify-center px-4">
      <div className="max-w-2xl w-full text-center space-y-8">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">{title || t("chat:welcomeTitle")}</h1>
          <p className="text-muted-foreground">{description || t("chat:welcomeDescription")}</p>
        </div>

        {suggestions.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left auto-rows-fr">
            {suggestions.map((suggestion, i) => (
              <button
                key={i}
                onClick={() => onSuggestionClick?.(suggestion)}
                className="p-3 rounded-xl border border-border hover:bg-muted transition-colors text-sm text-muted-foreground hover:text-foreground h-full flex items-center justify-center text-center"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function ChatWelcome({
  agentId,
  manifest,
  suggestions = [],
  onSuggestionClick,
}: ChatWelcomeProps) {
  // Build event for plugin
  const event: PluginEvent<WelcomeEventData> = {
    type: "welcome.render",
    pluginId: agentId,
    data: {
      title: manifest?.welcome?.title,
      description: manifest?.welcome?.description,
      suggestions: manifest?.welcome?.suggestions,
    },
  };

  // Try plugin-specific welcome
  const customWelcome = pluginEventBus.dispatch(event);

  if (customWelcome) {
    return <>{customWelcome}</>;
  }

  // Fallback - render from manifest data or use defaults
  return (
    <DefaultWelcome
      title={manifest?.welcome?.title}
      description={manifest?.welcome?.description}
      suggestions={
        manifest?.welcome?.suggestions?.map((s) => s.text) || suggestions
      }
      onSuggestionClick={onSuggestionClick}
    />
  );
}
