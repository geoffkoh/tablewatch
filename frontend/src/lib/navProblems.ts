/**
 * The nav's "Checks" badge (spec 039 P-D3): the count of active checks whose
 * latest outcome is `fail` or `error`. Every page that renders the shell
 * fetches it as a slot of its own, so Refresh reloads it with everything
 * else; its own loading or failure never changes what the rest of the page
 * shows (N3) — it is read only by `AppShell`, through `navProblemsCount`.
 */
import { listChecks } from "../api/api";
import type { CheckList } from "../api/types";
import type { Load } from "./useLoads";

export function fetchNavProblems(): Promise<CheckList> {
  return listChecks(["active"], ["fail", "error"]);
}

/** The badge's number, or null while loading, on failure, or when there is nothing to report. */
export function navProblemsCount(problems: Load<CheckList> | null): number | null {
  if (problems === null || problems.state !== "ok" || problems.data.total === 0) return null;
  return problems.data.total;
}
