import {
  referenceKey,
  type ComposerReference,
} from "@/utils/composerReferences";

/** Single autocomplete entry offered for the composer "@" mention. */
export interface ReferenceSuggestion {
  /** Reference added to the composer when the suggestion is picked. */
  reference: ComposerReference;
  /** Optional secondary line (e.g. document type) to distinguish duplicates. */
  description?: string;
}

export interface ReferenceSuggestionProvider {
  pluginId: string;
  priority: number;
  /**
   * Returns suggestions for the query typed after "@". An empty query means
   * "show recent/default entries". Implementations should honour the abort
   * signal for in-flight requests.
   */
  fetchSuggestions: (
    query: string,
    signal: AbortSignal,
  ) => Promise<ReferenceSuggestion[]>;
}

/**
 * Maps a rendered widget payload (e.g. source cards) to the references it
 * displays, so mention suggestions can prioritise documents already shown
 * in the conversation. Registered per widget type by the owning plugin.
 */
export interface ConversationReferenceExtractor {
  pluginId: string;
  widgetType: string;
  extract: (payload: Record<string, unknown>) => ComposerReference[];
}

class ReferenceSuggestionRegistry {
  private providers: ReferenceSuggestionProvider[] = [];
  private extractors: ConversationReferenceExtractor[] = [];
  private listeners = new Set<() => void>();

  register(provider: ReferenceSuggestionProvider): void {
    this.providers.push(provider);
    this.providers.sort((left, right) => left.priority - right.priority);
    this.notify();
  }

  registerExtractor(extractor: ConversationReferenceExtractor): void {
    this.extractors.push(extractor);
  }

  unregister(pluginId: string): void {
    this.providers = this.providers.filter(
      (provider) => provider.pluginId !== pluginId,
    );
    this.extractors = this.extractors.filter(
      (extractor) => extractor.pluginId !== pluginId,
    );
    this.notify();
  }

  /**
   * Subscribes to provider registration changes (for
   * `useSyncExternalStore`). Returns an unsubscribe function. Stable
   * reference (arrow property), safe to pass directly to React.
   */
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  /** References displayed by a widget payload; empty for unknown types. */
  extractConversationReferences(
    widgetType: string,
    payload: Record<string, unknown>,
  ): ComposerReference[] {
    const references: ComposerReference[] = [];
    for (const extractor of this.extractors) {
      if (extractor.widgetType !== widgetType) {
        continue;
      }
      try {
        references.push(...extractor.extract(payload));
      } catch (error) {
        console.warn(
          `Conversation reference extractor ${extractor.pluginId} failed:`,
          error,
        );
      }
    }
    return references;
  }

  hasProviders(): boolean {
    return this.providers.length > 0;
  }

  /**
   * Collects suggestions from all providers (provider order = priority),
   * skipping failing providers and deduplicating by reference identity.
   */
  async fetchSuggestions(
    query: string,
    signal: AbortSignal,
  ): Promise<ReferenceSuggestion[]> {
    const perProvider = await Promise.all(
      this.providers.map(async (provider) => {
        try {
          return await provider.fetchSuggestions(query, signal);
        } catch (error) {
          if (!signal.aborted) {
            console.warn(
              `Reference suggestion provider ${provider.pluginId} failed:`,
              error,
            );
          }
          return [];
        }
      }),
    );

    if (signal.aborted) {
      return [];
    }

    const seen = new Set<string>();
    const merged: ReferenceSuggestion[] = [];
    for (const suggestions of perProvider) {
      for (const suggestion of suggestions) {
        const key = referenceKey(suggestion.reference);
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);
        merged.push(suggestion);
      }
    }
    return merged;
  }

  getProviders(): ReferenceSuggestionProvider[] {
    return [...this.providers];
  }
}

export const referenceSuggestionRegistry = new ReferenceSuggestionRegistry();
