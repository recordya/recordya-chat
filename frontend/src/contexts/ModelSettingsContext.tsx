import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from "react";
import { getModelConfig, updateModelConfig, type ModelOption } from "@/lib/api";

interface ModelSettingsContextType {
  availableModels: ModelOption[];
  selectedModel: string;
  isLoading: boolean;
  setSelectedModel: (model: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const ModelSettingsContext = createContext<ModelSettingsContextType | undefined>(undefined);

export function ModelSettingsProvider({ children }: { children: ReactNode }) {
  const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelected] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const config = await getModelConfig();
      setAvailableModels(config.available);
      setSelected(config.selected);
    } catch {
      // Unauthenticated or backend unavailable — leave defaults; the backend
      // resolves the active model server-side when the chat omits it.
    } finally {
      setIsLoading(false);
    }
  }, []);

  const setSelectedModel = useCallback(async (model: string) => {
    const config = await updateModelConfig(model);
    setAvailableModels(config.available);
    setSelected(config.selected);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <ModelSettingsContext.Provider
      value={{ availableModels, selectedModel, isLoading, setSelectedModel, refresh }}
    >
      {children}
    </ModelSettingsContext.Provider>
  );
}

export function useModelSettings() {
  const context = useContext(ModelSettingsContext);
  if (!context) {
    throw new Error("useModelSettings must be used within ModelSettingsProvider");
  }
  return context;
}
