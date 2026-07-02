import { describe, it, expect } from "vitest";
import { parseSelectFieldMeta } from "./sqlParser";

describe("parseSelectFieldMeta", () => {
  it("returns empty for empty input", () => {
    expect(parseSelectFieldMeta("")).toEqual([]);
  });

  it("returns empty for non-SELECT statements (e.g. WITH/CTE)", () => {
    expect(parseSelectFieldMeta("WITH t AS (SELECT 1) SELECT * FROM t")).toEqual([]);
  });

  it("extracts plain column names", () => {
    const fields = parseSelectFieldMeta("SELECT title, author FROM audiobooks LIMIT 5");
    expect(fields.map((f) => f.key)).toEqual(["title", "author"]);
  });

  it("strips table prefixes from plain columns", () => {
    const fields = parseSelectFieldMeta("SELECT a.title, b.first_name FROM a JOIN b ON a.id = b.aid");
    expect(fields.map((f) => f.key)).toEqual(["title", "first_name"]);
  });

  it("uses explicit AS alias (unquoted)", () => {
    const fields = parseSelectFieldMeta("SELECT COUNT(*) AS total FROM t");
    expect(fields.map((f) => f.key)).toEqual(["total"]);
  });

  it("uses explicit AS alias (quoted, single word and multi-word)", () => {
    const fields = parseSelectFieldMeta(
      'SELECT n.full_name AS "Narrator", COUNT(*) AS "Audiobook count" FROM narrators n GROUP BY n.id'
    );
    expect(fields.map((f) => f.key)).toEqual(["Narrator", "Audiobook count"]);
  });

  it("ignores commas inside function calls", () => {
    const fields = parseSelectFieldMeta(
      "SELECT ROUND(AVG(x)::numeric, 2) AS average, COUNT(*) AS n FROM t"
    );
    expect(fields.map((f) => f.key)).toEqual(["average", "n"]);
  });

  it("handles subquery in SELECT and returns the outer alias (regression: title column NULL bug)", () => {
    const sql = [
      "SELECT",
      '  n.full_name AS "Narrator",',
      '  COUNT(DISTINCT an.id) AS "Audiobook count",',
      '  COUNT(DISTINCT p.name) AS "Platform count",',
      '  ROUND(AVG(an.duration_minutes)::numeric, 0) AS "Average duration",',
      "  (",
      "    SELECT an2.title",
      "    FROM audiobook_narrators anar2",
      "    JOIN audiobooks_normalized an2 ON anar2.audiobook_id = an2.id",
      "    JOIN ranking_entries re2 ON an2.id = re2.audiobook_id",
      "    WHERE anar2.narrator_id = n.id",
      "    LIMIT 1",
      '  ) AS "Most popular audiobook"',
      "FROM narrators n",
      "JOIN audiobook_narrators anar ON n.id = anar.narrator_id",
      "LIMIT 10",
    ].join("\n");

    const fields = parseSelectFieldMeta(sql);
    expect(fields.map((f) => f.key)).toEqual([
      "Narrator",
      "Audiobook count",
      "Platform count",
      "Average duration",
      "Most popular audiobook",
    ]);
  });

  it("handles multiple subqueries inside SELECT", () => {
    const sql =
      'SELECT a.id, (SELECT MAX(x) FROM b WHERE b.aid = a.id) AS "Max", ' +
      '(SELECT COUNT(*) FROM c WHERE c.aid = a.id) AS "Count" FROM a';
    const fields = parseSelectFieldMeta(sql);
    expect(fields.map((f) => f.key)).toEqual(["id", "Max", "Count"]);
  });

  it("filters out star (*)", () => {
    const fields = parseSelectFieldMeta("SELECT * FROM t");
    expect(fields).toEqual([]);
  });

  it("flags duration columns when configured", () => {
    const fields = parseSelectFieldMeta(
      'SELECT n.first_name AS "Narrator", SUM(duration_minutes) AS "Total" FROM t',
      { durationColumns: ["duration_minutes"] }
    );
    expect(fields).toEqual([
      { key: "Narrator", usesDurationColumn: false },
      { key: "Total", usesDurationColumn: true },
    ]);
  });

  it("marks duration column even when referenced through a table alias", () => {
    const fields = parseSelectFieldMeta(
      'SELECT an.title AS "Title", an.duration_minutes AS "Duration" FROM audiobooks_normalized an',
      { durationColumns: ["duration_minutes"] }
    );
    expect(fields).toEqual([
      { key: "Title", usesDurationColumn: false },
      { key: "Duration", usesDurationColumn: true },
    ]);
  });
});
