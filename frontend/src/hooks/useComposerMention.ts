import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  referenceSuggestionRegistry,
  type ReferenceSuggestion,
} from "@/plugins/ReferenceSuggestionRegistry";
import {
  detectMention,
  replaceMentionToken,
  type MentionQuery,
} from "@/utils/composerMention";
import {
  referenceKey,
  referenceToken,
  type ComposerReference,
} from "@/utils/composerReferences";

const DEBOUNCE_MS = 200;

interface UseComposerMentionOptions {
  input: string;
  setInput: (value: string) => void;
  addReference: (reference: ComposerReference) => void;
  /**
   * References already rendered in the conversation (e.g. on source cards).
   * They are surfaced as the first suggestion group, ahead of provider
   * results.
   */
  conversationReferences?: ComposerReference[];
}

/**
 * Composer "@" mention autocomplete: detects the token at the caret,
 * fetches suggestions (debounced, abortable) and handles keyboard
 * navigation. Picking a suggestion adds a chip and removes the token.
 *
 * Suggestions form two groups: references already shown in the conversation
 * first, then remaining provider results. `conversationCount` marks the
 * boundary inside the flat `suggestions` list.
 */
export function useComposerMention({
  input,
  setInput,
  addReference,
  conversationReferences = [],
}: UseComposerMentionOptions) {
  const [mention, setMention] = useState<MentionQuery | null>(null);
  const [fetchedSuggestions, setFetchedSuggestions] = useState<ReferenceSuggestion[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const close = useCallback(() => {
    abortRef.current?.abort();
    setMention(null);
    setFetchedSuggestions([]);
    setIsLoading(false);
    setActiveIndex(0);
  }, []);

  /** Re-evaluate the mention token from the composer text and caret offset. */
  const updateFromPosition = useCallback(
    (text: string, caret: number) => {
      if (!referenceSuggestionRegistry.hasProviders()) {
        return;
      }
      const detected = detectMention(text, caret);
      setMention((previous) => {
        if (!detected) {
          return null;
        }
        if (
          previous &&
          previous.start === detected.start &&
          previous.query === detected.query
        ) {
          return previous;
        }
        return detected;
      });
      if (!detected) {
        setFetchedSuggestions([]);
        setIsLoading(false);
        setActiveIndex(0);
      }
    },
    [],
  );

  useEffect(() => {
    if (!mention) {
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsLoading(true);
    const timer = setTimeout(async () => {
      const results = await referenceSuggestionRegistry.fetchSuggestions(
        mention.query,
        controller.signal,
      );
      if (controller.signal.aborted) {
        return;
      }
      setFetchedSuggestions(results);
      setActiveIndex(0);
      setIsLoading(false);
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [mention]);

  const { suggestions, conversationCount } = useMemo(() => {
    if (!mention) {
      return { suggestions: [] as ReferenceSuggestion[], conversationCount: 0 };
    }
    const query = mention.query.trim().toLowerCase();
    const descriptionByKey = new Map(
      fetchedSuggestions.map((suggestion) => [
        referenceKey(suggestion.reference),
        suggestion.description,
      ]),
    );
    const seen = new Set<string>();
    const conversation: ReferenceSuggestion[] = [];
    for (const reference of conversationReferences) {
      const key = referenceKey(reference);
      if (seen.has(key)) {
        continue;
      }
      if (query && !reference.label.toLowerCase().includes(query)) {
        continue;
      }
      seen.add(key);
      conversation.push({ reference, description: descriptionByKey.get(key) });
    }
    const others = fetchedSuggestions.filter(
      (suggestion) => !seen.has(referenceKey(suggestion.reference)),
    );
    return {
      suggestions: [...conversation, ...others],
      conversationCount: conversation.length,
    };
  }, [mention, fetchedSuggestions, conversationReferences]);

  const pick = useCallback(
    (suggestion: ReferenceSuggestion) => {
      if (mention) {
        setInput(
          replaceMentionToken(
            input,
            mention,
            referenceToken(suggestion.reference),
          ),
        );
      }
      addReference(suggestion.reference);
      close();
    },
    [mention, input, setInput, addReference, close],
  );

  /** Returns true when the event was consumed by the popover. */
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent): boolean => {
      if (!mention) {
        return false;
      }
      if (event.key === "Escape") {
        close();
        return true;
      }
      if (suggestions.length === 0) {
        return false;
      }
      if (event.key === "ArrowDown") {
        setActiveIndex((index) => (index + 1) % suggestions.length);
        return true;
      }
      if (event.key === "ArrowUp") {
        setActiveIndex(
          (index) => (index - 1 + suggestions.length) % suggestions.length,
        );
        return true;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        pick(suggestions[activeIndex]);
        return true;
      }
      return false;
    },
    [mention, suggestions, activeIndex, close, pick],
  );

  return {
    mention,
    suggestions,
    conversationCount,
    isLoading,
    activeIndex,
    setActiveIndex,
    updateFromPosition,
    handleKeyDown,
    pick,
    close,
  };
}
