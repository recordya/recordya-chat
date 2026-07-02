import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, Loader2, Check, AlertTriangle } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  toolRendererRegistry,
  type ToolRenderContext,
  type ToolRenderTarget,
} from "@/plugins/ToolRendererRegistry";
import type { ReasoningStep } from "@/hooks/useAgentStream";

interface ReasoningPanelProps {
  steps: ReasoningStep[];
  isStreaming?: boolean;
  agentId?: string;
  sourcePluginId?: string;
}

function formatDuration(ms?: number): string {
  if (ms === undefined || ms === null) {
    return "";
  }
  if (ms < 1000) {
    return `${ms} ms`;
  }
  return `${(ms / 1000).toFixed(1)} s`;
}

function StepIcon({ status }: { status: ReasoningStep["status"] }) {
  if (status === "running") {
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />;
  }
  if (status === "error") {
    return <AlertTriangle className="h-3.5 w-3.5 text-destructive" />;
  }
  return <Check className="h-3.5 w-3.5 text-muted-foreground" />;
}

interface ToolBlockProps {
  label: { open: string; closed: string };
  fallback: string | null;
  customNode: ReactNode | null;
}

function ToolBlock({ label, fallback, customNode }: ToolBlockProps) {
  const [open, setOpen] = useState(false);
  if (!customNode && !fallback) {
    return null;
  }
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1 text-[11px] text-muted-foreground/80 hover:text-foreground transition-colors">
        <ChevronRight
          className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span>{open ? label.open : label.closed}</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        {customNode ? (
          <div className="mt-1">{customNode}</div>
        ) : (
          <pre className="mt-1 max-h-64 overflow-auto rounded bg-muted/60 px-2 py-1 text-[11px] leading-snug whitespace-pre-wrap break-words text-muted-foreground">
            {fallback}
          </pre>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

interface StepRowProps {
  step: ReasoningStep;
  agentId?: string;
  sourcePluginId?: string;
}

function StepRow({ step, agentId, sourcePluginId }: StepRowProps) {
  const { t } = useTranslation();
  const reasoningText = step.reasoning?.trim() || step.message;
  const hasArgs = Object.keys(step.arguments).length > 0;
  const hasResult = !!step.result && Object.keys(step.result).length > 0;

  const renderContext: ToolRenderContext = {
    toolId: step.toolId,
    toolName: step.toolName,
    agentId,
    sourcePluginId,
    status: step.status,
    arguments: step.arguments,
    result: step.result,
    durationMs: step.durationMs,
    rowCount: step.rowCount,
    error: step.error,
  };

  const resolveBlock = (target: ToolRenderTarget, payloadEmpty: boolean) => {
    const decision = toolRendererRegistry.resolve(renderContext, target);
    if (decision.action === "hide") {
      return { render: false, customNode: null as ReactNode | null };
    }
    if (decision.action === "render" && decision.node) {
      return { render: true, customNode: decision.node };
    }
    return { render: !payloadEmpty, customNode: null };
  };

  const argsBlock = resolveBlock("arguments", !hasArgs);
  const resultBlock = resolveBlock("result", !hasResult);

  return (
    <div className="flex gap-2 text-xs">
      <div className="pt-0.5 shrink-0">
        <StepIcon status={step.status} />
      </div>
      <div className="flex-1 min-w-0 space-y-1">
        <div className="text-foreground/90">{reasoningText}</div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-muted-foreground">
          <span className="font-mono">{step.toolName}</span>
          {step.durationMs !== undefined && (
            <span>· {formatDuration(step.durationMs)}</span>
          )}
          {step.rowCount !== undefined && step.rowCount !== null && (
            <span>· {t("reasoning:rows", { count: step.rowCount })}</span>
          )}
          {step.error && (
            <span className="text-destructive">· {step.error}</span>
          )}
        </div>
        {argsBlock.render && (
          <ToolBlock
            label={{ closed: t("reasoning:showArgs"), open: t("reasoning:hideArgs") }}
            fallback={hasArgs ? JSON.stringify(step.arguments, null, 2) : null}
            customNode={argsBlock.customNode}
          />
        )}
        {resultBlock.render && (
          <ToolBlock
            label={{ closed: t("reasoning:showResult"), open: t("reasoning:hideResult") }}
            fallback={hasResult ? JSON.stringify(step.result, null, 2) : null}
            customNode={resultBlock.customNode}
          />
        )}
      </div>
    </div>
  );
}

export function ReasoningPanel({
  steps,
  isStreaming = false,
  agentId,
  sourcePluginId,
}: ReasoningPanelProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);

  if (steps.length === 0) {
    return null;
  }

  const completed = steps.filter((s) => s.status !== "running").length;
  const total = steps.length;
  const headerLabel = isStreaming
    ? t("reasoning:thinking", { completed, total })
    : t("reasoning:thought", { count: total });

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="w-full">
      <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
        <ChevronRight
          className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span>{headerLabel}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-2 border-l border-border/60 pl-3 space-y-2">
        {steps.map((step) => (
          <StepRow
            key={step.toolId}
            step={step}
            agentId={agentId}
            sourcePluginId={sourcePluginId}
          />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}
