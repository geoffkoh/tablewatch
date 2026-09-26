import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";
import { ApiError, getProject, listChecks, listRuns, type ApiFailure } from "../api/api";
import type { CheckList, Project, RunPage } from "../api/types";
import { CheckTable } from "../components/CheckTable";
import { Header } from "../components/Header";
import { LatestRun } from "../components/LatestRun";
import { LoadError } from "../components/LoadError";
import { ProjectProblems } from "../components/ProjectProblems";
import { Summary } from "../components/Summary";

type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "failed"; failure: ApiFailure };

interface Results {
  checks: CheckList;
  runs: RunPage;
}

function failureOf(error: unknown): ApiFailure {
  if (error instanceof ApiError) return error.failure;
  return { kind: "network", message: "Something went wrong while loading. Try again." };
}

/** Ages move on while the page is open; re-render them once a minute. No data is fetched. */
const TICK_MS = 60_000;

export function Overview(): ReactElement {
  const [project, setProject] = useState<Load<Project>>({ state: "loading" });
  const [results, setResults] = useState<Load<Results>>({ state: "loading" });
  const [busy, setBusy] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const generation = useRef(0);

  const load = useCallback(() => {
    // Only the newest refresh may write state: an older answer arriving late is dropped.
    generation.current += 1;
    const mine = generation.current;
    const current = (): boolean => mine === generation.current;
    setBusy(true);
    const projectRequest = getProject().then(
      (data) => {
        if (current()) setProject({ state: "ok", data });
      },
      (error: unknown) => {
        if (current()) setProject({ state: "failed", failure: failureOf(error) });
      },
    );
    const resultsRequest = Promise.all([listChecks(), listRuns(1)]).then(
      ([checks, runs]) => {
        if (current()) setResults({ state: "ok", data: { checks, runs } });
      },
      (error: unknown) => {
        if (current()) setResults({ state: "failed", failure: failureOf(error) });
      },
    );
    void Promise.all([projectRequest, resultsRequest]).then(() => {
      if (current()) {
        setNow(Date.now());
        setBusy(false);
      }
    });
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, TICK_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [load]);

  const loadedProject = project.state === "ok" ? project.data : null;

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || results.state === "failed") status = "Could not load everything.";
  else status = "Up to date.";

  return (
    <>
      <Header project={loadedProject} now={now} busy={busy} onRefresh={load} />
      <main id="main" className="page" tabIndex={-1} aria-busy={busy}>
        <p className="visually-hidden" role="status">
          {status}
        </p>
        {project.state === "failed" && <LoadError what="the project" failure={project.failure} onRetry={load} />}
        {loadedProject !== null && <ProjectProblems project={loadedProject} />}
        {results.state === "failed" && <LoadError what="results" failure={results.failure} onRetry={load} />}
        {(project.state === "loading" || results.state === "loading") &&
          project.state !== "failed" &&
          results.state !== "failed" && <p className="loading">Loading…</p>}
        {loadedProject !== null && results.state === "ok" && (
          <>
            <div className="overview-grid">
              <Summary project={loadedProject} checks={results.data.checks.items} />
              <LatestRun run={results.data.runs.items[0] ?? null} now={now} />
            </div>
            <CheckTable
              checks={results.data.checks.items}
              newestRunId={results.data.runs.items[0]?.id ?? null}
              now={now}
            />
          </>
        )}
      </main>
    </>
  );
}
