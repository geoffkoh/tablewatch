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
