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
 * section lives in `components/check/`. An eighth slot, `problems`, feeds
 * the shell's nav badge only (spec 039 P-D3); its own state never changes
 * what this page shows.
 *
 * `/checks/{id}` answers with `state: "retired"` for a check gone from the
 * project's files but kept in the store (spec 037 S13): its header is
 * `RetiredIdentity`, not `Identity`, and it has no rule, SQL or source
 * sections — its latest result and history still show, as for any check.
 */
import { useEffect, useMemo, useRef, type ReactElement } from "react";
import { getCheck, getCheckSource, getCheckSql, getDefinitions, getHistory, getProject, isNotFound, listRuns } from "../api/api";
import type { CheckDetailItem, CheckList, CheckSource, CheckSql, DefinitionList, HistoryPage, Project, RunPage } from "../api/types";
import { AppShell } from "../components/AppShell";
import { DefinitionSection } from "../components/check/DefinitionSection";
import { HistorySection } from "../components/check/HistorySection";
import { Identity } from "../components/check/Identity";
import { LatestSection } from "../components/check/LatestSection";
import { NotFoundPanel } from "../components/check/NotFoundPanel";
import { RetiredIdentity } from "../components/check/RetiredIdentity";
import { RuleSection } from "../components/check/RuleSection";
import { SourceSection } from "../components/check/SourceSection";
import { SqlSection } from "../components/check/SqlSection";
import { HISTORY_LIMIT, useOlderHistory } from "../components/check/useOlderHistory";
import { LoadError } from "../components/LoadError";
import { fetchNavProblems } from "../lib/navProblems";
import { useLoads, type Requests } from "../lib/useLoads";

interface CheckSlots {
  project: Project;
  check: CheckDetailItem;
  history: HistoryPage;
  runs: RunPage;
  sql: CheckSql;
  source: CheckSource;
  definitions: DefinitionList;
  problems: CheckList;
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
      definitions: () => getDefinitions(id),
      problems: fetchNavProblems,
    }),
    [id],
  );
  const { slots, busy, now, generation, reload, capture } = useLoads(requests);
  const { project, check, history, runs, sql, source, definitions, problems } = slots;

  const loadedProject = project.state === "ok" ? project.data : null;
  const loadedItem = check.state === "ok" ? check.data : null;
  // A retired check (spec 037 S13) is a successful response, never
  // `checkMissing`: it has no file, rule or SQL any more, but it is not 404.
  const loadedCheck = loadedItem !== null && loadedItem.state !== "retired" ? loadedItem : null;
  const retiredCheck = loadedItem !== null && loadedItem.state === "retired" ? loadedItem : null;
  const checkMissing = check.state === "failed" && isNotFound(check.failure);
  const firstPage = history.state === "ok" ? history.data : null;
  const older = useOlderHistory({ id, firstPage, busy, generation, capture });
  const { entries } = older;
  const newestRunId = runs.state === "ok" ? (runs.data.items[0]?.id ?? null) : null;

  const newest = entries[0];
  const pending = loadedCheck !== null && newest !== undefined && newest.expression !== loadedCheck.expression;

  const name = loadedCheck?.name ?? retiredCheck?.name ?? (checkMissing ? (newest?.name ?? null) : null);
  useEffect(() => {
    document.title = `${name ?? (checkMissing && history.state === "failed" ? "Check not found" : "Check")} · tablewatch`;
  }, [name, checkMissing, history.state]);

  // What the page can say about the check.
  const notLoadedButRecorded = checkMissing && firstPage !== null && entries.length > 0;
  const unknown = checkMissing && history.state === "failed" && isNotFound(history.failure);
  // A 404 from /sql means "no longer loaded" when /checks/{id} is 404 too (P6, P7),
  // or, for a retired check (S9), is expected: it has no file to compile.
  const sqlFailed = sql.state === "failed" && !((checkMissing || retiredCheck !== null) && isNotFound(sql.failure));
  // The same rule for /source (spec 006, P7; spec 037 S9).
  const sourceFailed = source.state === "failed" && !((checkMissing || retiredCheck !== null) && isNotFound(source.failure));
  // The SQL and Source sections wait for /checks/{id}, are absent for an id
  // nobody knows (P6), and for a retired check (S13: no SQL or source tabs).
  const showSql = check.state !== "loading" && !unknown && !(checkMissing && history.state === "loading") && retiredCheck === null;
  const showSource = showSql;
  // The Definition section (spec 038 S8) comes from the results store, not a
  // check file, so a retired check has one too — the one condition it drops
  // from `showSql`. A 404 from /definitions means "no row at all" only when
  // the check is unknown; it is never expected for a retired check.
  const showDefinitions = check.state !== "loading" && !unknown && !(checkMissing && history.state === "loading");
  const definitionsFailed = definitions.state === "failed" && !(checkMissing && isNotFound(definitions.failure));

  let status: string;
  if (busy) status = "Loading…";
  else if (
    project.state === "failed" ||
    (check.state === "failed" && !checkMissing) ||
    history.state === "failed" ||
    sqlFailed ||
    sourceFailed ||
    definitionsFailed
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
    <AppShell
      current="checks"
      project={loadedProject}
      now={now}
      busy={busy}
      onRefresh={reload}
      problems={problems}
      projectIsHeading={false}
    >
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

        {retiredCheck !== null && (
          <>
            <RetiredIdentity check={retiredCheck} now={now} />
            <LatestSection check={retiredCheck} newestRunId={newestRunId} judgedBy={null} now={now} />
          </>
        )}

        {(loadedCheck !== null || retiredCheck !== null || notLoadedButRecorded) && (
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

        {showDefinitions && (
          <DefinitionSection definitions={definitions} checkMissing={checkMissing} now={now} onRetry={reload} />
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
    </AppShell>
  );
}
