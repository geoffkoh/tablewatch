/**
 * What changed between two definition versions (spec 038, Q4 data-steward).
 * Clauses are matched by `key` (stable, chosen by the author), never by
 * clause id (which itself changes when `where`/options change what is
 * measured): a key only in the new version is added, a key only in the old
 * one is removed, a key in both with the same expression, `where` and
 * options (deep-equal, ignoring the options object's key order) is not
 * shown, and a key in both that differs in any of the three is changed,
 * carrying both clauses in full so the caller can show old → new. A clause's
 * options are part of its identity: a version is recorded when one changes
 * (e.g. `valid_values: [a, b, c]` → `[a, b]`) even though no option appears
 * in `expression`, so leaving them out of the comparison would show "no
 * change" for a real one. Reordering clauses, or re-quoting/re-spacing an
 * option with the same meaning, is never a change: the fingerprint that
 * decides whether a version exists already ignores both (`definitions.py`),
 * and this match is by key, never by position.
 */
import type { Definition, DefinitionClause } from "../api/types";

export type ClauseChangeKind = "added" | "removed" | "changed";

export interface ClauseChange {
  key: string;
  kind: ClauseChangeKind;
  /** The clause as it was; null for "added". */
  before: DefinitionClause | null;
  /** The clause as it is now; null for "removed". */
  after: DefinitionClause | null;
}

/** An option's text, as written: a string plain, anything else JSON-like. */
function renderOptionValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return `[${value.map(renderOptionValue).join(", ")}]`;
  if (value === null) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Past this many characters, an option (typically a `query:`/`condition:`) gets its own line. */
const LONG_OPTION = 48;

/**
 * The clause's full rendered text: its expression, `where` when set, and
 * its options after that in a compact `key: value` form, each sorted by
 * key for a stable order. A long option's line (commonly a SQL `query:` or
 * `condition:`) is broken onto its own line rather than packed in with the
 * rest; short ones share a line with the expression.
 */
export function renderClause(clause: DefinitionClause): string {
  const head = clause.where === null ? clause.expression : `${clause.expression} where ${clause.where}`;
  const keys = Object.keys(clause.options).sort();
  if (keys.length === 0) return head;
  const inline: string[] = [];
  const own: string[] = [];
  for (const key of keys) {
    const text = `${key}: ${renderOptionValue(clause.options[key])}`;
    (text.length > LONG_OPTION ? own : inline).push(text);
  }
  const first = inline.length === 0 ? head : `${head}; ${inline.join("; ")}`;
  return own.length === 0 ? first : `${first}\n${own.join("\n")}`;
}

/** Deep equality, ignoring an object's key order (arrays stay order-sensitive: a list is a list). */
function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => sameValue(v, b[i]));
  }
  if (typeof a === "object" && a !== null && typeof b === "object" && b !== null) {
    const ak = Object.keys(a as Record<string, unknown>);
    const bk = Object.keys(b as Record<string, unknown>);
    return (
      ak.length === bk.length &&
      ak.every((k) => k in (b as Record<string, unknown>) && sameValue((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]))
    );
  }
  return false;
}

/** A clause's identity for this diff: expression, `where`, and its options (deep-equal). */
function sameClause(a: DefinitionClause, b: DefinitionClause): boolean {
  return a.expression === b.expression && a.where === b.where && sameValue(a.options, b.options);
}

/**
 * `previous`'s clauses vs. `current`'s, in `current`'s file order, added or
 * changed first, then any key removed from `previous` (in `previous`'s file
 * order). `previous` is null for a definition's first version, which has no
 * diff — the caller shows its clauses instead of a change list.
 */
export function diffDefinition(previous: Definition | null, current: Definition): ClauseChange[] {
  if (previous === null) return [];
  const before = new Map(previous.clauses.map((c) => [c.key, c] as const));
  const after = new Set(current.clauses.map((c) => c.key));
  const changes: ClauseChange[] = [];
  for (const clause of current.clauses) {
    const prior = before.get(clause.key);
    if (prior === undefined) changes.push({ key: clause.key, kind: "added", before: null, after: clause });
    else if (!sameClause(prior, clause)) changes.push({ key: clause.key, kind: "changed", before: prior, after: clause });
  }
  for (const clause of previous.clauses) {
    if (!after.has(clause.key)) changes.push({ key: clause.key, kind: "removed", before: clause, after: null });
  }
  return changes;
}
