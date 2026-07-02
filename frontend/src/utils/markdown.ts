/**
 * Convert bullet points (•) to markdown list markers (-) for proper rendering.
 * Preserves original line spacing from LLM output.
 */
export function convertBulletsToMarkdown(text: string): string {
  // Replace • or · at start of line with - for markdown list
  // Don't add extra newlines - preserve original spacing
  return text.replace(/^[•·]\s*/gm, "- ");
}

/**
 * Remove markdown table syntax from text.
 * Tables are already displayed via ResultsTable component, so we strip them from the summary.
 */
export function stripMarkdownTables(text: string): string {
  // Remove lines that look like markdown table rows (start and end with |)
  return text
    .split("\n")
    .filter((line) => !line.trim().match(/^\|.*\|$/))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n"); // Clean up multiple newlines
}
