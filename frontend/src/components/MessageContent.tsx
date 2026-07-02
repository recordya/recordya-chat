/**
 * MessageContent - Renders message content through TransformRegistry.
 *
 * This component applies all registered transformers and renderers
 * to the message content before displaying it.
 *
 * @example
 * <MessageContent content="Hello **world**" />
 */

import { useMemo } from "react";
import { transformRegistry, type TransformContext } from "@/plugins/registry";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { convertBulletsToMarkdown } from "@/utils/markdown";

interface MessageContentProps {
  /** Raw content to render */
  content: string;
  /** Optional message ID for context */
  messageId?: string;
  /** Optional agent ID for context */
  agentId?: string;
  /** Plugin that produced the message (exposed to transforms via context). */
  sourcePluginId?: string;
  /** Whether the message also carries rendered results (exposed to transforms via context). */
  hasResults?: boolean;
  /** Whether the message is still streaming */
  isStreaming?: boolean;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Decode HTML entities like &quot; &amp; etc.
 */
function decodeHtmlEntities(text: string): string {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = text;
  return textarea.value;
}

/**
 * Default markdown renderer used when no custom renderer is registered.
 */
function DefaultMarkdownRenderer({ content }: { content: string }) {
  const prepared = convertBulletsToMarkdown(decodeHtmlEntities(content));
  return (
    <ReactMarkdown remarkPlugins={[remarkBreaks, remarkGfm]}>
      {prepared}
    </ReactMarkdown>
  );
}

export function MessageContent({
  content,
  messageId,
  agentId,
  sourcePluginId,
  hasResults = false,
  isStreaming = false,
  className = "",
}: MessageContentProps) {
  // Build context for transformers
  const context: TransformContext = useMemo(
    () => ({
      messageId,
      agentId,
      sourcePluginId,
      hasResults,
      isStreaming,
    }),
    [messageId, agentId, sourcePluginId, hasResults, isStreaming]
  );

  // Apply transformations and render (memoized for performance)
  const renderedContent = useMemo(() => {
    // Check if any custom renderers are registered
    const renderers = transformRegistry.getRenderers();

    if (renderers.length > 0) {
      // Use TransformRegistry's render method which applies transformers + first matching renderer
      return transformRegistry.render(content, context);
    }

    // Fallback: apply text transformers then use default markdown renderer
    const transformed = transformRegistry.transform(content, context);
    return <DefaultMarkdownRenderer content={transformed} />;
  }, [content, context]);

  return (
    <div
      className={`text-sm text-foreground prose prose-sm dark:prose-invert max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-2 prose-strong:text-foreground ${className}`}
    >
      {renderedContent}
    </div>
  );
}

export default MessageContent;

