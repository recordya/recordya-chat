/**
 * Extracts field metadata from a SELECT clause.
 *
 * Lets the frontend format values based on the *source* column rather than the
 * output alias (e.g. `SUM(czas_trwania_minuty) AS suma_minut` is still a duration).
 * Source-column recognition is plugin-driven via {@link ParseSelectFieldMetaOptions.durationColumns}.
 */
export interface SelectFieldMeta {
  /** Output field name (alias or column name). */
  key: string;
  /** Whether the SELECT expression references one of the configured duration columns. */
  usesDurationColumn: boolean;
}

export interface ParseSelectFieldMetaOptions {
  /** Database column names whose values are durations expressed in minutes. */
  durationColumns?: readonly string[];
}

function splitSelectFields(selectPart: string): string[] {
  // Split on commas, but ignore commas nested inside function calls.
  const fields: string[] = [];
  let current = "";
  let parenDepth = 0;

  for (const char of selectPart) {
    if (char === "(") parenDepth++;
    else if (char === ")") parenDepth--;
    else if (char === "," && parenDepth === 0) {
      fields.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }

  if (current.trim()) fields.push(current.trim());
  return fields;
}

// Identifier pattern that also accepts diacritics used by some locales (e.g. Polish columns).
const IDENT = '[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ_][a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ0-9_]*';

function stripQuotes(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function extractOutputKey(fieldExpr: string): string {
  let trimmed = fieldExpr.trim();

  // Remove DISTINCT, ALL etc. keywords at the start.
  trimmed = trimmed.replace(/^(DISTINCT|ALL)\s+/i, "");

  // Alias with AS (case insensitive); supports identifiers with diacritics.
  const asMatch = trimmed.match(
    new RegExp(`\\s+AS\\s+["']?(${IDENT})["']?\\s*$`, 'i')
  );
  if (asMatch) return asMatch[1];

  // Alias with AS, quoted (e.g. AS "ocena_lektora_na_BookBeat").
  const asQuotedMatch = trimmed.match(/\s+AS\s+("([^"]+)"|'([^']+)')\s*$/i);
  if (asQuotedMatch) return stripQuotes(asQuotedMatch[1]);

  // Implicit alias without AS (e.g. COUNT(*) total).
  const implicitAlias = trimmed.match(
    new RegExp(`\\)\\s+(${IDENT})$`)
  );
  if (implicitAlias) return implicitAlias[1];

  // Implicit alias without AS, quoted (e.g. COUNT(*) "Total").
  const implicitQuotedAlias = trimmed.match(/\)\s+("([^"]+)"|'([^']+)')\s*$/);
  if (implicitQuotedAlias) return stripQuotes(implicitQuotedAlias[1]);

  // Plain column (optionally with a table prefix); returns only the column name.
  const simpleMatch = trimmed.match(
    new RegExp(`^(?:${IDENT}\\.)?(${IDENT})$`)
  );
  if (simpleMatch) return simpleMatch[1];

  // Plain column with quotes (e.g. "column" or "table"."column").
  const quotedSimpleMatch = trimmed.match(
    new RegExp(
      `^(?:"([^"]+)"|(${IDENT}))(?:\\.(?:"([^"]+)"|(${IDENT})))?$`
    )
  );
  if (quotedSimpleMatch) {
    // With a table prefix the column is in group 3 or 4.
    const column = quotedSimpleMatch[3] || quotedSimpleMatch[4];
    // Without a prefix the column is in group 1 or 2.
    return (column || quotedSimpleMatch[1] || quotedSimpleMatch[2] || "").trim();
  }

  // Function call without alias - fall back to the function name.
  const funcMatch = trimmed.match(/^(\w+)\s*\(/);
  if (funcMatch) return funcMatch[1].toLowerCase();

  // Fallback: take the last whitespace-separated token, stripping any table prefix.
  const words = trimmed.split(/\s+/);
  const lastWord = stripQuotes(words[words.length - 1].replace(/[()]/g, ""));
  return lastWord.replace(/^\w+\./, "");
}

function usesColumn(expr: string, columnName: string): boolean {
  // Detect a column reference (with optional table prefix); aliases are ignored.
  const re = new RegExp(`(?:\\b\\w+\\.)?\\b${columnName}\\b`, "i");
  return re.test(expr);
}

function findTopLevelFromIndex(normalizedSql: string, startIndex: number): number {
  // Walk the string tracking parenthesis depth so subqueries do not match.
  let parenDepth = 0;
  for (let i = startIndex; i < normalizedSql.length; i++) {
    const ch = normalizedSql[i];
    if (ch === "(") parenDepth++;
    else if (ch === ")") parenDepth--;
    else if (
      parenDepth === 0 &&
      (ch === "F" || ch === "f") &&
      normalizedSql.slice(i, i + 4).toUpperCase() === "FROM" &&
      /\s/.test(normalizedSql[i - 1] ?? "") &&
      /\s/.test(normalizedSql[i + 4] ?? "")
    ) {
      return i;
    }
  }
  return -1;
}

export function parseSelectFieldMeta(
  sql: string,
  options?: ParseSelectFieldMetaOptions
): SelectFieldMeta[] {
  if (!sql) return [];

  const durationColumns = options?.durationColumns ?? [];

  const normalizedSql = sql.replace(/\s+/g, " ").trim();
  const selectStartMatch = normalizedSql.match(/^SELECT\s+/i);
  if (!selectStartMatch) return [];

  const selectStart = selectStartMatch[0].length;
  const fromIndex = findTopLevelFromIndex(normalizedSql, selectStart);
  if (fromIndex === -1) return [];

  const selectPart = normalizedSql.slice(selectStart, fromIndex).trim();
  const rawFields = splitSelectFields(selectPart);

  return rawFields
    .map((expr) => {
      const key = extractOutputKey(expr);
      return {
        key,
        usesDurationColumn: durationColumns.some((column) => usesColumn(expr, column)),
      } satisfies SelectFieldMeta;
    })
    .filter((f) => f.key && f.key.length > 0 && f.key !== "*");
}

