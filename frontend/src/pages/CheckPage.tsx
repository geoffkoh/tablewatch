/**
 * A check's page, `/checks/<id>` (spec 004): what the check is, its rule,
 * its latest result in the overview's words, and its history as a chart and
 * a table, then the SQL a run of its dataset sends (spec 005). Loads
 * `/project`, `/checks/{id}`, `/checks/{id}/history?limit=200`, `/runs?limit=1`,
 * `/checks/{id}/sql` and `/checks/{id}/source` through the shared hook; Refresh
 * reloads all six and drops any older pages. The check's own YAML lines follow
 * the SQL (spec 006).
 *
 * This module decides which sections the page shows from what loaded; each
 * section lives in `components/check/`.
 */
import { useEffect, useMemo, useRef, type ReactElement } from "react";
import { getCheck, getCheckSource, getCheckSql, getHistory, getProject, isNotFound, listRuns } from "../api/api";
import type { CheckDetail, CheckSource, CheckSql, HistoryPage, Project, RunPage } from "../api/types";
import { HistorySection } from "../components/check/HistorySection";
import { Identity } from "../components/check/Identity";
import { LatestSection } from "../components/check/LatestSection";
import { NotFoundPanel } from "../components/check/NotFoundPanel";
import { RuleSection } from "../components/check/RuleSection";
import { SourceSection } from "../components/check/SourceSection";
import { SqlSection } from "../components/check/SqlSection";
import { HISTORY_LIMIT, useOlderHistory } from "../components/check/useOlderHistory";
import { Header } from "../components/Header";
import { LoadError } from "../components/LoadError";
import { useLoads, type Requests } from "../lib/useLoads";

interface CheckSlots {
  project: Project;
  check: CheckDetail;
  history: HistoryPage;
  runs: RunPage;
  sql: CheckSql;
  source: CheckSource;
}

/**
 * The fragments that link to a section, and the section's id (spec 005 P11,
 * spec 006 P11). The sections are not on the page when the browser looks.
 */
export const FRAGMENTS: ReadonlyMap<string, string> = new Map([
  ["#sql", "sql"],
  ["#source", "source"],
]);

export function CheckPage({ id }: { id: string }): ReactElement {
  const requests = useMemo<Requests<CheckSlots>>(
    () => ({
      project: getProject,
      check: () => getCheck(id),
      history: () => getHistory(id, HISTORY_LIMIT),
      runs: () => listRuns(1),
      sql: () => getCheckSql(id),
      source: () => getCheckSource(id),
    }),
    [id],
  );
  const { slots, busy, now, generation, reload, capture } = useLoads(requests);
  const { project, check, history, runs, sql, source } = slots;

  const loadedProject = project.state === "ok" ? project.data : null;
  const loadedCheck = check.state === "ok" ? check.data : null;
  const checkMissing = check.state === "failed" && isNotFound(check.failure);
  const firstPage = history.state === "ok" ? history.data : null;
  const older = useOlderHistory({ id, firstPage, busy, generation, capture });
  const { entries } = older;
  const newestRunId = runs.state === "ok" ? (runs.data.items[0]?.id ?? null) : null;

  const newest = entries[0];
  const pending = loadedCheck !== null && newest !== undefined && newest.expression !== loadedCheck.expression;

  const name = loadedCheck?.name ?? (checkMissing ? (newest?.name ?? null) : null);
  useEffect(() => {
    document.title = `${name ?? (checkMissing && history.state === "failed" ? "Check not found" : "Check")} · tablewatch`;
  }, [name, checkMissing, history.state]);

  // What the page can say about the check.
  const notLoadedButRecorded = checkMissing && firstPage !== null && entries.length > 0;
  const unknown = checkMissing && history.state === "failed" && isNotFound(history.failure);
  // A 404 from /sql means "no longer loaded" only when /checks/{id} is 404 too (P6, P7).
  const sqlFailed = sql.state === "failed" && !(checkMissing && isNotFound(sql.failure));
  // The same rule for /source (spec 006, P7).
  const sourceFailed = source.state === "failed" && !(checkMissing && isNotFound(source.failure));
  // The SQL and Source sections wait for /checks/{id}, and are absent for an id nobody knows (P6).
  const showSql = check.state !== "loading" && !unknown && !(checkMissing && history.state === "loading");
  const showSource = showSql;

  let status: string;
  if (busy) status = "Loading…";
  else if (
    project.state === "failed" ||
    (check.state === "failed" && !checkMissing) ||
    history.state === "failed" ||
    sqlFailed ||
    sourceFailed
  )
    status = "Could not load everything.";
  else status = "Up to date.";

  // `/checks/<id>#sql` or `#source`: the section is not on the page when the
  // browser looks for the fragment, so scroll to it once, after the first
  // round settles (P11).
  const scrolled = useRef(false);
  useEffect(() => {
    if (busy || scrolled.current) return;
    scrolled.current = true;
    const target = FRAGMENTS.get(window.location.hash);
    if (target !== undefined) document.getElementById(target)?.scrollIntoView();
  }, [busy]);

  return (
    <>
      <Header project={loadedProject} now={now} busy={busy} onRefresh={reload} projectIsHeading={false} />
      <main id="main" className="page" tabIndex={-1} aria-busy={busy}>
        <p className="visually-hidden" role="status">
          {status}
        </p>
        <p className="back">
          <a href="/">Back to the overview</a>
        </p>
        {project.state === "failed" && <LoadError what="the project" failure={project.failure} onRetry={reload} />}

        {check.state === "loading" && <p className="loading">Loading…</p>}
        {check.state === "failed" && !checkMissing && (
          <>
            <h1 className="check-title">
              Check <code>{id}</code>
            </h1>
            <LoadError what="the check" failure={check.failure} onRetry={reload} />
          </>
        )}
        {unknown && <NotFoundPanel id={id} projectBroken={loadedProject !== null && !loadedProject.ok} />}
        {checkMissing && !unknown && !notLoadedButRecorded && (
          <>
            <h1 className="check-title">
              Check <code>{id}</code>
            </h1>
            {history.state === "loading" && <p className="loading">Loading…</p>}
            {history.state === "failed" && <LoadError what="the history" failure={history.failure} onRetry={reload} />}
          </>
        )}
        {notLoadedButRecorded && (
          <section className="panel" aria-labelledby="check-heading">
            <h1 id="check-heading" className="check-title">
              {newest?.name ?? id}
            </h1>
            <p className="pending-note" data-note="not-loaded">
              This check is no longer in the loaded check files. Its recorded results are below. The id is{" "}
              <code>{id}</code>.
            </p>
          </section>
        )}

        {loadedCheck !== null && (
          <>
            <Identity check={loadedCheck} sourceLinked={showSource} />
            <div className="detail-grid">
              <RuleSection check={loadedCheck} project={loadedProject} pending={pending} now={now} />
              <LatestSection
                check={loadedCheck}
                newestRunId={newestRunId}
                judgedBy={pending && newest !== undefined ? newest.expression : null}
                now={now}
              />
            </div>
          </>
        )}

        {(loadedCheck !== null || notLoadedButRecorded) && (
          <HistorySection
            id={id}
            name={name}
            check={loadedCheck}
            history={history}
            older={older}
            pending={pending}
            now={now}
            onRetry={reload}
          />
        )}

        {showSql && (
          <SqlSection sql={sql} unit={loadedCheck?.unit ?? null} checkMissing={checkMissing} onRetry={reload} />
        )}

        {showSource && (
          <SourceSection
            source={source}
            metric={loadedCheck?.metric ?? null}
            checkMissing={checkMissing}
            now={now}
            onRetry={reload}
          />
        )}
      </main>
    </>
  );
}
