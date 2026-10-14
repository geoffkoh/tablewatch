import { useEffect, type ReactElement } from "react";
import { getProject, listChecks, listRuns } from "../api/api";
import type { CheckList, CheckSummary, Project, RunPage } from "../api/types";
import { AppShell } from "../components/AppShell";
import { CheckTable } from "../components/CheckTable";
import { LatestRun } from "../components/LatestRun";
import { LoadError } from "../components/LoadError";
import { ProjectProblems } from "../components/ProjectProblems";
import { Summary } from "../components/Summary";
import { isRetired } from "../lib/explorer";
import { fetchNavProblems } from "../lib/navProblems";
import { notLoadedFromRun } from "../lib/status";
import { useLoads, type Requests } from "../lib/useLoads";

interface Results {
  checks: CheckList;
  runs: RunPage;
}

/**
 * The overview never asks for retired checks (`listChecks()` with no
 * `states`, spec 037 S7: unchanged response), so `CheckList.items` holds
 * `CheckSummary` only here — this narrows the type to match what the server
 * actually sends.
 */
function loadedChecks(items: CheckList["items"]): CheckSummary[] {
  return items.filter((item): item is CheckSummary => !isRetired(item));
}

interface OverviewSlots {
  project: Project;
  results: Results;
  problems: CheckList;
}

// Checks and the newest run are one slot: either failing hides both (O9).
// `problems` feeds the nav's Checks badge only (P-D3); its own state never
// changes what this page shows (N3).
const REQUESTS: Requests<OverviewSlots> = {
  project: getProject,
  results: () => Promise.all([listChecks(), listRuns(1)]).then(([checks, runs]) => ({ checks, runs })),
  problems: fetchNavProblems,
};

export function Overview(): ReactElement {
  const { slots, busy, now, reload } = useLoads(REQUESTS);
  const { project, results, problems } = slots;
  const loadedProject = project.state === "ok" ? project.data : null;
  const latestRun = results.state === "ok" ? (results.data.runs.items[0] ?? null) : null;
  const checks = results.state === "ok" ? loadedChecks(results.data.checks.items) : [];
  const notLoaded = results.state === "ok" ? notLoadedFromRun(latestRun, checks) : 0;

  useEffect(() => {
    if (loadedProject !== null) document.title = `Dashboard — ${loadedProject.name}`;
  }, [loadedProject]);

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || results.state === "failed") status = "Could not load everything.";
  else status = "Up to date.";

  return (
    <AppShell current="dashboard" project={loadedProject} now={now} busy={busy} onRefresh={reload} problems={problems}>
      <p className="visually-hidden" role="status">
        {status}
      </p>
      {project.state === "failed" && <LoadError what="the project" failure={project.failure} onRetry={reload} />}
      {loadedProject !== null && <ProjectProblems project={loadedProject} notLoaded={notLoaded} />}
      {results.state === "failed" && <LoadError what="results" failure={results.failure} onRetry={reload} />}
      {(project.state === "loading" || results.state === "loading") &&
        project.state !== "failed" &&
        results.state !== "failed" && <p className="loading">Loading…</p>}
      {loadedProject !== null && results.state === "ok" && (
        <>
          <div className="overview-grid">
            <Summary project={loadedProject} checks={checks} />
            <LatestRun run={latestRun} now={now} notLoaded={notLoaded} projectOk={loadedProject.ok} />
          </div>
          <CheckTable checks={checks} newestRunId={latestRun?.id ?? null} now={now} />
        </>
      )}
    </AppShell>
  );
}
