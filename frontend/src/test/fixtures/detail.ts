/**
 * Check-page responses for spec 004's fixture states. The shapes and values
 * match what `tablewatch serve` answered on a scratch copy of
 * examples/retail on 2026-09-26 (the `rule` of every check below was read
 * from `GET /api/v1/checks/{id}`); ids and times are the placeholders of
 * `states.ts` (A 06:55:50, B 06:56:12, E 06:56:30, F 06:56:45 UTC).
 *
 * Typed against the generated contract: a contract change breaks `tsc` here.
 */
import type { CheckDetail, CheckSummary, HistoryEntry, HistoryPage, Rule } from "../../api/types";
import { beforeF, interrupted, recorded, RUN_ID, STARTED, type OverviewResponses } from "./states";

const compare = (op: "=" | "!=" | "<" | "<=" | ">" | ">=", value: number, text: string) =>
  ({ kind: "compare", op, value, text }) as const;

/** `rule` as the server serves it for the retail checks used here. */
export const RULES: Readonly<Record<string, Rule>> = {
  b1ceb8262d8b5441: { expect: compare("<", 5, "< 5%"), warn: null, fail: null },
  "32c8f939b90f6367": { expect: compare(">", 0, "> 0"), warn: null, fail: null },
  "41e58afff9c48a46": { expect: null, warn: compare(">", 86400, "> 1d"), fail: compare(">", 604800, "> 7d") },
  "32867fbe86f483f3": { expect: null, warn: compare("<", 100, "< 100"), fail: compare("=", 0, "= 0") },
  "366d9254d889c910": {
    expect: { kind: "between", low: 10, high: 500, negated: false, text: "between 10 and 500" },
    warn: null,
    fail: null,
  },
  cd3e8103b4318809: {
    expect: { kind: "between", low: 1, high: 10000, negated: false, text: "between 1 and 10000" },
    warn: null,
    fail: null,
  },
  a81b0374b0b04f06: { expect: compare("<", 21600, "< 6h"), warn: null, fail: null },
  fbc3aa0b93b66eee: { expect: compare("=", 0, "= 0"), warn: null, fail: null },
  ed669ca6e5532a59: { expect: compare("=", 0, "= 0"), warn: null, fail: null },
  "000f8d0048744bfb": { expect: compare("=", 0, "= 0"), warn: null, fail: null },
};

function summaryOf(state: OverviewResponses, id: string): CheckSummary {
  const found = state.checks.items.find((c) => c.id === id);
  if (found === undefined) throw new Error(`no check ${id} in the fixture`);
  return structuredClone(found);
}

/** `GET /checks/{id}` for a check in a captured state. */
export function detailOf(state: OverviewResponses, id: string): CheckDetail {
  const rule = RULES[id];
  if (rule === undefined) throw new Error(`no rule for ${id}`);
  return { ...summaryOf(state, id), rule: structuredClone(rule) };
}

type Run = keyof typeof RUN_ID | "C" | "M" | "N";

export const EXTRA_RUN_ID = {
  C: "c0000000000000000000000000000005",
  M: "d0000000000000000000000000000006",
  N: "90000000000000000000000000000007",
} as const;

export const EXTRA_STARTED = {
  C: "2026-09-26T07:30:00.000000+00:00",
  M: "2026-09-26T08:00:00.000000+00:00",
  N: "2026-09-26T08:30:00.000000+00:00",
} as const;

function runId(run: Run): string {
  return run in RUN_ID ? RUN_ID[run as keyof typeof RUN_ID] : EXTRA_RUN_ID[run as keyof typeof EXTRA_RUN_ID];
}

function started(run: Run): string {
  return run in STARTED ? STARTED[run as keyof typeof STARTED] : EXTRA_STARTED[run as keyof typeof EXTRA_STARTED];
}

/** One history entry for a check, as recorded in a run. */
export function entry(check: CheckSummary, run: Run, fields: Partial<HistoryEntry> = {}): HistoryEntry {
  return {
    run_id: runId(run),
    started_at: started(run),
    trigger: "cli",
    outcome: "pass",
    value: 0,
    display_value: "0",
    message: null,
    duration_ms: 3.2,
    name: check.name,
    expression: check.expression,
    source: check.source,
    metric: check.metric,
    dataset: check.dataset,
    unit: check.unit,
    ...fields,
  };
}

export function page(items: HistoryEntry[], nextCursor: string | null = null): HistoryPage {
  return { items, next_cursor: nextCursor };
}

const IO_ERROR = (() => {
  const e = beforeF.checks.items.find((c) => c.id === "b1ceb8262d8b5441")?.latest?.message;
  if (e == null) throw new Error("beforeF has no IO error");
  return e;
})();
export { IO_ERROR };

const email = summaryOf(interrupted, "b1ceb8262d8b5441");
const rows = summaryOf(interrupted, "32c8f939b90f6367");

const fail20 = { outcome: "fail", value: 20, display_value: "20.00%", message: "expected < 5%" } as const;
const error = { outcome: "error", value: null, display_value: "—", message: IO_ERROR } as const;

/** `interrupted`, `/checks/b1ceb8262d8b5441/history`: F fail, E error, B fail, A fail. */
export const emailHistory = page([
  entry(email, "F", fail20),
  entry(email, "E", error),
  entry(email, "B", fail20),
  entry(email, "A", fail20),
]);

/** `interrupted`, `/checks/32c8f939b90f6367/history`: F pass, E error, B pass, A pass. */
export const rowsHistory = page([
  entry(rows, "F", { value: 5, display_value: "5" }),
  entry(rows, "E", error),
  entry(rows, "B", { value: 5, display_value: "5" }),
  entry(rows, "A", { value: 5, display_value: "5" }),
]);

/** A-B-E (`beforeF`): the latest result is the error. */
export const emailHistoryBeforeF = page(emailHistory.items.slice(1));

// ---- edited, edited-pending, metric-changed ----------------------------------

export const EDITED_ID = "customer-email-completeness";
const EXPR_5 = "missing_percent(email) < 5%";
const EXPR_15 = "missing_percent(email) < 15%";
const EXPR_25 = "missing_percent(email) < 25%";
const EXPR_COUNT = "missing_count(email) = 0";

function editedCheck(expression: string, rule: Rule, latest: CheckSummary["latest"]): CheckDetail {
  return {
    ...email,
    id: EDITED_ID,
    name: expression,
    expression,
    latest,
    rule,
  };
}

const at = (run: Run, fields: Partial<HistoryEntry>): HistoryEntry =>
  entry({ ...email, name: fields.expression ?? EXPR_5, expression: fields.expression ?? EXPR_5 }, run, fields);

const editedA = at("A", { ...fail20, expression: EXPR_5, name: EXPR_5 });
const editedC = at("C", { ...fail20, message: "expected < 15%", expression: EXPR_15, name: EXPR_15 });

const latestC = {
  run_id: EXTRA_RUN_ID.C,
  started_at: EXTRA_STARTED.C,
  since: STARTED.A,
  trigger: "cli",
  outcome: "fail",
  value: 20,
  display_value: "20.00%",
  message: "expected < 15%",
  last_evaluated: null,
} as const;

/** `edited`: A under `< 5%`, C under `< 15%`, loaded as `< 15%`. */
export const edited = {
  check: editedCheck(EXPR_15, { expect: compare("<", 15, "< 15%"), warn: null, fail: null }, { ...latestC }),
  history: page([editedC, editedA]),
};

/** `edited-pending`: `edited`, then the file says `< 25%` and no run has used it. */
export const editedPending = {
  check: editedCheck(EXPR_25, { expect: compare("<", 25, "< 25%"), warn: null, fail: null }, { ...latestC }),
  history: page([editedC, editedA]),
};

const editedM = at("M", {
  outcome: "fail",
  value: 1,
  display_value: "1",
  message: "expected = 0",
  expression: EXPR_COUNT,
  name: EXPR_COUNT,
  metric: "missing_count",
  unit: "count",
});
const editedN = at("N", { ...fail20, message: "expected < 15%", expression: EXPR_15, name: EXPR_15 });

/** `metric-changed`, then back to `< 15%` and run N (D20). */
export const metricChangedBack = {
  check: editedCheck(
    EXPR_15,
    { expect: compare("<", 15, "< 15%"), warn: null, fail: null },
    { ...latestC, run_id: EXTRA_RUN_ID.N, started_at: EXTRA_STARTED.N },
  ),
  history: page([editedN, editedM, editedC, editedA]),
};

/** D8: three rules; A passed under `< 25%` although 20 is in today's failing region. */
export const threeRules = {
  check: edited.check,
  history: page([
    at("C", { ...fail20, message: "expected < 15%", expression: EXPR_15, name: EXPR_15 }),
    at("B", { ...fail20, expression: EXPR_5, name: EXPR_5 }),
    at("A", { outcome: "pass", value: 20, display_value: "20.00%", message: null, expression: EXPR_25, name: EXPR_25 }),
  ]),
};

// ---- recorded ---------------------------------------------------------------

/** `recorded`: a check's history is its latest result in runs A and B (or A alone). */
export function recordedHistory(id: string): HistoryPage {
  const check = summaryOf(recorded, id);
  const latest = check.latest;
  if (latest === null) return page([]);
  const fields = {
    outcome: latest.outcome,
    value: latest.value,
    display_value: latest.display_value,
    message: latest.message,
  };
  return latest.run_id === RUN_ID.B
    ? page([entry(check, "B", fields), entry(check, "A", fields)])
    : page([entry(check, "A", fields)]);
}

export { email as emailSummary };

// ---- spec 012 ---------------------------------------------------------------

/**
 * `avg-on-nothing` (spec 012 L1): `avg(amount) between 10 and 500` with a
 * `where:` no row matches. `latest` is what `GET /api/v1/checks/avg-on-nothing`
 * answered on a scratch retail copy on 2026-09-29; ids and times are the
 * placeholders of `states.ts`.
 */
export const AVG_ON_NOTHING_ID = "avg-on-nothing";

export const avgOnNothing: { check: CheckDetail; history: HistoryPage } = (() => {
  const base = detailOf(recorded, "366d9254d889c910");
  const latest = {
    run_id: RUN_ID.B,
    started_at: STARTED.B,
    since: STARTED.B,
    trigger: "cli",
    outcome: "fail",
    value: null,
    display_value: "—",
    message: "no non-NULL values in scope",
    last_evaluated: null,
  } as const;
  const check: CheckDetail = { ...base, id: AVG_ON_NOTHING_ID, latest: { ...latest } };
  const fields = { outcome: "fail", value: null, display_value: "—", message: latest.message } as const;
  return { check, history: page([entry(check, "B", fields)]) };
})();
