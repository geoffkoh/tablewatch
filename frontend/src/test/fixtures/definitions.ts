/**
 * Builders for `Definition`/`DefinitionList` (spec 038), typed against the
 * generated contract: a contract change breaks `tsc` here.
 */
import type { Definition, DefinitionClause, DefinitionList } from "../../api/types";

export function clause(key: string, expression: string, fields: Partial<DefinitionClause> = {}): DefinitionClause {
  return { key, expression, where: null, options: {}, ...fields };
}

export function version(
  versionNumber: number,
  recordedAt: string,
  runId: string | null,
  clauses: DefinitionClause[],
): Definition {
  return { version: versionNumber, recorded_at: recordedAt, run_id: runId, clauses };
}

/** Newest first, as the API answers (spec 038 S6). */
export function definitions(items: Definition[]): DefinitionList {
  return { items };
}
