import { ResultsTable } from "@/components/ResultsTable";
import type { ResultRenderContext } from "@/plugins/ResultRegistry";

interface DefaultResultsTableWidgetProps {
  context: ResultRenderContext;
  pageSize?: number;
}

export function DefaultResultsTableWidget({ context, pageSize }: DefaultResultsTableWidgetProps) {
  return (
    <ResultsTable
      data={context.queryResults}
      fields={context.fields}
      durationFields={context.durationFields}
      pageSize={pageSize}
    />
  );
}
