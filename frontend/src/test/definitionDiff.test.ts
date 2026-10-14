/**
 * `diffDefinition` and `renderClause` (spec 038, Q4 data-steward): matching
 * clauses by `key`, added/removed/changed, and what reordering or re-quoting
 * must never trigger.
 */
import { describe, expect, it } from "vitest";
import { diffDefinition, renderClause } from "../lib/definitionDiff";
import { clause, version } from "./fixtures/definitions";

const AT = "2026-09-26T06:55:50.000000+00:00";

describe("renderClause: expression, `where`, then options", () => {
  it("is just the expression when where is null and there are no options", () => {
    expect(renderClause(clause("row_count", "row_count > 0"))).toBe("row_count > 0");
  });

  it("appends 'where <text>' when where is set", () => {
    expect(renderClause(clause("amount", "avg(amount) between 1 and 500", { where: "reason != 'damaged'" }))).toBe(
      "avg(amount) between 1 and 500 where reason != 'damaged'",
    );
  });

  it("appends short options inline, compactly, sorted by key", () => {
    expect(
      renderClause(clause("a", "valid_count(status)", { options: { allow_blank: false, valid_values: ["a", "b", "c"] } })),
    ).toBe("valid_count(status); allow_blank: false; valid_values: [a, b, c]");
  });

  it("a long option (a SQL query or condition) gets its own line", () => {
    const query = "SELECT count(*) FROM orders WHERE status = 'void' AND created_at > now() - interval '1 day'";
    expect(renderClause(clause("a", "sql_metric", { options: { query } }))).toBe(`sql_metric\nquery: ${query}`);
  });

  it("mixes a short inline option with a long one on its own line", () => {
    const query = "SELECT count(*) FROM orders WHERE status = 'void' AND created_at > now() - interval '1 day'";
    expect(renderClause(clause("a", "sql_metric", { options: { label: "void orders", query } }))).toBe(
      `sql_metric; label: void orders\nquery: ${query}`,
    );
  });
});

describe("diffDefinition: matching by key", () => {
  it("the first version (previous is null) has no diff", () => {
    const v1 = version(1, AT, "run-a", [clause("row_count", "row_count > 0")]);
    expect(diffDefinition(null, v1)).toEqual([]);
  });

  it("a key only in the new version is added", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "missing_count(email) = 0")]);
    const v2 = version(2, AT, "run-b", [clause("a", "missing_count(email) = 0"), clause("b", "row_count > 0")]);
    expect(diffDefinition(v1, v2)).toEqual([{ key: "b", kind: "added", before: null, after: v2.clauses[1] }]);
  });

  it("a key only in the old version is removed", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "missing_count(email) = 0"), clause("b", "row_count > 0")]);
    const v2 = version(2, AT, "run-b", [clause("a", "missing_count(email) = 0")]);
    expect(diffDefinition(v1, v2)).toEqual([{ key: "b", kind: "removed", before: v1.clauses[1], after: null }]);
  });

  it("a key in both with the same expression and where is not shown", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "row_count > 0", { where: "status = 'ok'" })]);
    const v2 = version(2, AT, "run-b", [clause("a", "row_count > 0", { where: "status = 'ok'" })]);
    expect(diffDefinition(v1, v2)).toEqual([]);
  });

  it("a different expression is changed, carrying both clauses in full", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "missing_percent(email) < 5%")]);
    const v2 = version(2, AT, "run-b", [clause("a", "missing_percent(email) < 15%")]);
    expect(diffDefinition(v1, v2)).toEqual([{ key: "a", kind: "changed", before: v1.clauses[0], after: v2.clauses[0] }]);
  });

  it("a different where (same expression) is changed too", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "avg(amount) between 1 and 500")]);
    const v2 = version(2, AT, "run-b", [clause("a", "avg(amount) between 1 and 500", { where: "reason != 'damaged'" })]);
    expect(diffDefinition(v1, v2)).toEqual([{ key: "a", kind: "changed", before: v1.clauses[0], after: v2.clauses[0] }]);
  });

  it("reordering clauses with no other change is not a change", () => {
    const a = clause("a", "row_count > 0");
    const b = clause("b", "missing_count(email) = 0");
    const v1 = version(1, AT, "run-a", [a, b]);
    const v2 = version(2, AT, "run-b", [b, a]);
    expect(diffDefinition(v1, v2)).toEqual([]);
  });

  it("a changed option is a change, although the expression and where are identical", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "valid_count(status)", { options: { valid_values: ["a", "b", "c"] } })]);
    const v2 = version(2, AT, "run-b", [clause("a", "valid_count(status)", { options: { valid_values: ["a", "b"] } })]);
    expect(diffDefinition(v1, v2)).toEqual([{ key: "a", kind: "changed", before: v1.clauses[0], after: v2.clauses[0] }]);
  });

  it("the same options in a different key order is not a change", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "row_count > 0", { options: { b: 2, a: 1 } })]);
    const v2 = version(2, AT, "run-b", [clause("a", "row_count > 0", { options: { a: 1, b: 2 } })]);
    expect(diffDefinition(v1, v2)).toEqual([]);
  });

  it("an option's array order is still significant (a list is a list, unlike the options object)", () => {
    const v1 = version(1, AT, "run-a", [clause("a", "valid_count(status)", { options: { valid_values: ["a", "b"] } })]);
    const v2 = version(2, AT, "run-b", [clause("a", "valid_count(status)", { options: { valid_values: ["b", "a"] } })]);
    expect(diffDefinition(v1, v2)).toHaveLength(1);
  });

  it("added and changed come first in the new version's order, removed last in the old's", () => {
    const v1 = version(1, AT, "run-a", [
      clause("gone", "row_count > 0"),
      clause("moved", "missing_count(email) = 0"),
    ]);
    const v2 = version(2, AT, "run-b", [
      clause("moved", "missing_count(email) = 5"),
      clause("new", "duplicate_count(id) = 0"),
    ]);
    expect(diffDefinition(v1, v2).map((c) => c.key)).toEqual(["moved", "new", "gone"]);
  });
});
