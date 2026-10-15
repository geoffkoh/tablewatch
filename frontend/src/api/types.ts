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
export type RecordedClause = Schemas["RecordedClause"];
/** A check gone from the project's files (spec 037): `GET /checks` with `?state=retired`, or `GET /checks/{id}` for its id. */
export type RetiredCheckSummary = Schemas["RetiredCheckSummary"];
/** One item of `CheckList.items`: active, disabled or retired, discriminated on `state`. */
export type CheckListItem = CheckList["items"][number];
/** Every `state` `GET /checks` accepts, repeatable (spec 037). */
export type CheckState = CheckListItem["state"];
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
/** Every value `GET /checks`'s `?outcome=` filter accepts, repeatable (spec 039 P-D3): a recorded outcome, or `not_run` for a check with no result. */
export type OutcomeFilter = Outcome | "not_run";

export type CheckDetail = Schemas["CheckDetail"];
/** What `GET /checks/{id}` serves: a loaded check's detail, or a retired check's summary (spec 037). */
export type CheckDetailItem = CheckDetail | RetiredCheckSummary;
export type Rule = Schemas["Rule"];
export type CompareCondition = Schemas["CompareCondition"];
export type BetweenCondition = Schemas["BetweenCondition"];
/** One side of a rule: `expect`, `warn` or `fail`. */
export type Condition = CompareCondition | BetweenCondition;
export type HistoryEntry = Schemas["HistoryEntry"];
export type HistoryPage = Schemas["HistoryPage"];
/** One version of a check's definition (spec 038), newest first in `DefinitionList`. */
export type Definition = Schemas["Definition"];
/** One clause of a definition version, as it was written. */
export type DefinitionClause = Schemas["DefinitionClause"];
export type DefinitionList = Schemas["DefinitionList"];
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

/** A check's own lines, as loaded (spec 006). `start_line`, `end_line` and `text` are null together when the span is unavailable. */
export type CheckSource = Schemas["CheckSource"];
/** The check file's dataset `filter:`; `applies` is false for metrics it never scopes. */
export type FileFilter = Schemas["FileFilter"];

/** `GET /settings`'s shape (spec 040): the project as loaded, read-only and without credentials. */
export type Settings = Schemas["Settings"];
export type SettingsProject = Schemas["SettingsProject"];
export type SettingsDatasource = Schemas["SettingsDatasource"];
export type SettingsNotifier = Schemas["SettingsNotifier"];
export type SettingsResults = Schemas["SettingsResults"];
export type SettingsChecks = Schemas["SettingsChecks"];

/** `GET /alerts`'s shape (spec 041): a result that changed its check's state, newest first. */
export type Alert = Schemas["Alert"];
export type AlertPage = Schemas["AlertPage"];
/** The check as the registry has it, shared by alerts and check changes: a retired one's outlive it. */
export type CheckRef = Schemas["CheckRef"];
export type AlertDelivery = Schemas["AlertDelivery"];
/** `failing`, `erroring` or `recovered` — `results.state.transition`'s events (P1). */
export type AlertEvent = Alert["event"];

/** `GET /check-changes`'s shape (spec 042): a recent change to a check, newest first. */
export type CheckChange = Schemas["CheckChange"];
export type CheckChangeList = Schemas["CheckChangeList"];
/** `added`, `redefined`, `disabled`, `retired` or `enabled` (K-D4). */
export type ChangeKind = CheckChange["kind"];
