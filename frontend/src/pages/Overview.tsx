import type { ReactElement } from "react";
import { getProject, listChecks, listRuns } from "../api/api";
import type { CheckList, Project, RunPage } from "../api/types";
import { CheckTable } from "../components/CheckTable";
import { Header } from "../components/Header";
import { LatestRun } from "../components/LatestRun";
import { LoadError } from "../components/LoadError";
import { ProjectProblems } from "../components/ProjectProblems";
import { Summary } from "../components/Summary";
import { notLoadedFromRun } from "../lib/status";
import { useLoads, type Requests } from "../lib/useLoads";

interface Results {
  checks: CheckList;
  runs: RunPage;
}

interface OverviewSlots {
  project: Project;
  results: Results;
}

// Checks and the newest run are one slot: either failing hides both (O9).
const REQUESTS: Requests<OverviewSlots> = {
  project: getProject,
  results: () => Promise.all([listChecks(), listRuns(1)]).then(([checks, runs]) => ({ checks, runs })),
};

export function Overview(): ReactElement {
  const { slots, busy, now, reload } = useLoads(REQUESTS);
  const { project, results } = slots;
  const loadedProject = project.state === "ok" ? project.data : null;
  const latestRun = results.state === "ok" ? (results.data.runs.items[0] ?? null) : null;
  const notLoaded = results.state === "ok" ? notLoadedFromRun(latestRun, results.data.checks.items) : 0;

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || results.state === "failed") status = "Could not load everything.";
  else status = "Up to date.";

  return (
    <>
      <Header project={loadedProject} now={now} busy={busy} onRefresh={reload} />
      <main id="main" className="page" tabIndex={-1} aria-busy={busy}>
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
              <Summary project={loadedProject} checks={results.data.checks.items} />
              <LatestRun
                run={latestRun}
                now={now}
                notLoaded={notLoaded}
                projectOk={loadedProject.ok}
              />
            </div>
            <CheckTable
              checks={results.data.checks.items}
              newestRunId={latestRun?.id ?? null}
              now={now}
            />
          </>
        )}
      </main>
    </>
  );
}
