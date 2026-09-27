/**
 * Names for the API's shapes. Every type here is an alias into the generated
 * `schema.gen.ts` (from docs/api/openapi.json), never a hand-written copy, so
 * a contract change breaks `tsc` rather than the page.
 */
import type { components } from "./schema.gen";

type Schemas = components["schemas"];

export type Project = Schemas["Project"];
export type Diagnostic = Schemas["Diagnostic"];
export type Location = Schemas["Location"];
export type CheckList = Schemas["CheckList"];
export type CheckSummary = Schemas["CheckSummary"];
export type LatestResult = Schemas["LatestResult"];
export type LastEvaluated = Schemas["LastEvaluated"];
export type RunPage = Schemas["RunPage"];
export type Run = Schemas["Run"];
export type Counts = Schemas["Counts"];
export type Selection = Run["selection"];
export type ErrorBody = Schemas["ErrorBody"];
export type ErrorCode = Schemas["ErrorInfo"]["code"];

/** A recorded outcome, as the API sends it. */
export type Outcome = LatestResult["outcome"];

export type CheckDetail = Schemas["CheckDetail"];
export type Rule = Schemas["Rule"];
export type CompareCondition = Schemas["CompareCondition"];
export type BetweenCondition = Schemas["BetweenCondition"];
/** One side of a rule: `expect`, `warn` or `fail`. */
export type Condition = CompareCondition | BetweenCondition;
export type HistoryEntry = Schemas["HistoryEntry"];
export type HistoryPage = Schemas["HistoryPage"];
/** A metric's unit; `null` on a history entry whose metric this version does not know. */
export type Unit = CheckSummary["unit"];

export type CheckSql = Schemas["CheckSql"];
export type ScanStatement = Schemas["ScanStatement"];
export type QueryStatement = Schemas["QueryStatement"];
export type ScanColumn = Schemas["ScanColumn"];
/**
 * One statement of `CheckSql`. The union is open on `kind` (spec 005, A4): a
 * later server may send a kind this client does not know, and the page skips
 * it (P15), so code narrows on `kind` and never assumes the list is exhaustive.
 */
export type Statement = CheckSql["statements"][number];
