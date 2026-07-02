import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ResultsTable } from "./ResultsTable";

const ROWS = Array.from({ length: 15 }, (_, index) => ({ name: `row-${index}` }));

describe("ResultsTable pagination", () => {
  it("defaults to 10 rows per page", () => {
    const html = renderToStaticMarkup(
      <ResultsTable data={ROWS} fields={["name"]} />,
    );
    expect(html).toContain("row-9");
    expect(html).not.toContain("row-10");
    expect(html).toContain("Page 1 of 2");
  });

  it("renders up to pageSize rows on a single page when pageSize covers all rows", () => {
    const html = renderToStaticMarkup(
      <ResultsTable data={ROWS} fields={["name"]} pageSize={20} />,
    );
    expect(html).toContain("row-14");
    expect(html).not.toContain("Page 1 of");
  });
});
