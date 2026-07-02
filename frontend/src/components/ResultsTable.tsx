import { useState, useMemo, useEffect, useRef } from "react";
import { ChevronLeft, ChevronRight, Maximize2, Minimize2 } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { formatValue, formatLabel, type FormatValueOptions } from "@/utils/formatters";
import { useFormatConfig } from "@/plugins/registry";
import { useTranslation } from "react-i18next";

interface ResultsTableProps {
  data: Record<string, unknown>[];
  fields: string[];
  durationFields?: string[];
  pageSize?: number;
}

const DEFAULT_PAGE_SIZE = 10;

function calculateProportionalWidths(data: Record<string, unknown>[], fields: string[]): number[] {
  const minWidthPercent = 8; // Minimum column width in %

  const weights = fields.map((field) => {
    let maxChars = formatLabel(field).length;
    data.slice(0, 50).forEach((row) => {
      const value = String(row[field] ?? "");
      maxChars = Math.max(maxChars, Math.min(value.length, 60));
    });
    return Math.max(4, maxChars);
  });

  const totalWeight = weights.reduce((sum, w) => sum + w, 0);
  const rawWidths = weights.map((w) => (w / totalWeight) * 100);

  // Apply minimum width
  const adjustedWidths = rawWidths.map((w) => Math.max(minWidthPercent, w));
  const adjustedTotal = adjustedWidths.reduce((sum, w) => sum + w, 0);

  // Normalize to 100% if exceeded
  if (adjustedTotal > 100) {
    const scale = 100 / adjustedTotal;
    return adjustedWidths.map((w) => w * scale);
  }
  
  return adjustedWidths;
}

function calculateExpandedWidths(data: Record<string, unknown>[], fields: string[]): number[] {
  return fields.map((field) => {
    let maxChars = formatLabel(field).length;
    data.slice(0, 100).forEach((row) => {
      const value = String(row[field] ?? "");
      maxChars = Math.max(maxChars, value.length);
    });
    // About 7px per char + padding, minimum 60px
    return Math.max(60, maxChars * 7 + 16);
  });
}

function calculateMinWidths(fields: string[]): number[] {
  // Minimum column width so the header is fully readable.
  // When the sum exceeds the container width, the wrapper scrolls horizontally.
  return fields.map((field) => {
    const labelChars = formatLabel(field).length;
    return Math.max(80, labelChars * 8 + 24);
  });
}

export function ResultsTable({ data, fields, durationFields, pageSize = DEFAULT_PAGE_SIZE }: ResultsTableProps) {
  const { t } = useTranslation();
  const [currentPage, setCurrentPage] = useState(1);
  const [isExpanded, setIsExpanded] = useState(false);

  const formatConfig = useFormatConfig();
  const formatOptions = useMemo<FormatValueOptions>(
    () => ({
      locale: formatConfig.locale,
      durationLabels: formatConfig.durationLabels,
      durationFields,
    }),
    [formatConfig, durationFields]
  );

  const displayFields = useMemo(
    () => (fields.length > 0 ? fields : Object.keys(data[0] || {})),
    [fields, data]
  );
  
  const proportionalWidths = useMemo(
    () => calculateProportionalWidths(data, displayFields),
    [data, displayFields]
  );
  
  const expandedWidths = useMemo(
    () => calculateExpandedWidths(data, displayFields),
    [data, displayFields]
  );

  const minWidths = useMemo(
    () => calculateMinWidths(displayFields),
    [displayFields]
  );

  const wrapperRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  useEffect(() => {
    const node = wrapperRef.current;
    if (!node) return;
    setContainerWidth(node.clientWidth);
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Column widths in pixels: proportional to the container, but not less than the minimum.
  // When the sum > container, the wrapper scrolls horizontally.
  const pixelWidths = useMemo(() => {
    if (containerWidth <= 0) return null;
    return proportionalWidths.map((p, i) =>
      Math.max(minWidths[i], Math.round((p / 100) * containerWidth))
    );
  }, [containerWidth, proportionalWidths, minWidths]);

  const totalPixelWidth = useMemo(
    () => (pixelWidths ? pixelWidths.reduce((sum, w) => sum + w, 0) : 0),
    [pixelWidths]
  );
  
  const totalResults = data.length;
  const totalPages = Math.ceil(totalResults / pageSize);

  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalResults);
  const currentData = data.slice(startIndex, endIndex);

  // Reset expanded state when data/fields change
  useEffect(() => {
    setIsExpanded(false);
  }, [data, displayFields]);

  const goToPage = (page: number) => {
    setCurrentPage(Math.max(1, Math.min(page, totalPages)));
  };

  const toggleExpanded = () => {
    setIsExpanded(!isExpanded);
  };

  // Compute style for a column
  const getColumnStyle = (index: number) => {
    if (isExpanded) {
      return { width: expandedWidths[index] };
    }
    if (pixelWidths) {
      return { width: pixelWidths[index] };
    }
    return {
      width: `${proportionalWidths[index]}%`,
      minWidth: minWidths[index],
    };
  };

  // Table style
  const tableStyle = isExpanded
    ? { tableLayout: 'fixed' as const, width: 'max-content', minWidth: '100%' }
    : {
        tableLayout: 'fixed' as const,
        width: totalPixelWidth > 0 ? totalPixelWidth : '100%',
      };

  return (
    <div className="space-y-3">
      {/* Header with results count and expand button */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>
            {t("chat:resultsCount", { count: totalResults })}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={toggleExpanded}
            className="h-6 w-6 p-0"
            title={isExpanded ? t("chat:collapseColumns") : t("chat:expandColumns")}
          >
            {isExpanded ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
        {totalPages > 1 && (
          <span>
            {t("chat:pageOf", { current: currentPage, total: totalPages })}
          </span>
        )}
      </div>

      {/* Table */}
      <div ref={wrapperRef} className="rounded-lg border overflow-x-auto">
        <Table style={tableStyle}>
          <TableHeader>
            <TableRow className="bg-muted/50">
              {displayFields.map((field, index) => (
                <TableHead 
                  key={field}
                  className="text-xs font-medium py-1.5"
                  style={getColumnStyle(index)}
                >
                  <span className="truncate block" title={formatLabel(field)}>
                    {formatLabel(field)}
                  </span>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {currentData.map((row, rowIndex) => (
              <TableRow key={rowIndex} className="h-9">
                {displayFields.map((field, colIndex) => {
                  const displayValue = formatValue(row[field], field, formatOptions);
                  return (
                    <TableCell 
                      key={field} 
                      className="text-xs py-1"
                      style={getColumnStyle(colIndex)}
                    >
                      <span className="truncate block" title={displayValue}>
                        {displayValue}
                      </span>
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {t("chat:showingResults", { start: startIndex + 1, end: endIndex, total: totalResults })}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage === 1}
              className="h-8 px-2"
            >
              <ChevronLeft className="h-4 w-4" />
              <span className="sr-only">{t("chat:previous")}</span>
            </Button>

            {/* Page numbers */}
            <div className="flex items-center gap-1">
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 5) {
                  pageNum = i + 1;
                } else if (currentPage <= 3) {
                  pageNum = i + 1;
                } else if (currentPage >= totalPages - 2) {
                  pageNum = totalPages - 4 + i;
                } else {
                  pageNum = currentPage - 2 + i;
                }
                return (
                  <Button
                    key={pageNum}
                    variant={currentPage === pageNum ? "default" : "outline"}
                    size="sm"
                    onClick={() => goToPage(pageNum)}
                    className="h-8 w-8 p-0"
                  >
                    {pageNum}
                  </Button>
                );
              })}
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage === totalPages}
              className="h-8 px-2"
            >
              <ChevronRight className="h-4 w-4" />
              <span className="sr-only">{t("chat:next")}</span>
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
