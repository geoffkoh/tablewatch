/**
 * A check's page, `/checks/<id>` (spec 004): what the check is, its rule,
 * its latest result in the overview's words, and its history as a chart and
 * a table. Loads `/project`, `/checks/{id}`, `/checks/{id}/history?limit=200`
 * and `/runs?limit=1` through the shared hook; Refresh reloads all four and
 * drops any older pages.
 */
import { useEffect, useMemo, useState, type ReactElement } from "react";
import { failureOf, getCheck, getHistory, getProject, isNotFound, listRuns, type ApiFailure } from "../api/api";
import type { CheckDetail, HistoryEntry, HistoryPage, Project, RunPage } from "../api/types";
import { HistoryFigure } from "../components/chart/HistoryFigure";
import { Header } from "../components/Header";
import { HistoryTable } from "../components/HistoryTable";
import { Result, When } from "../components/LatestResult";
import { LoadError } from "../components/LoadError";
import { StatusBadge } from "../components/StatusIcon";
import { Ago } from "../components/Time";
import { layoutChart } from "../lib/chart/layout";
import { chartSummary } from "../lib/chart/summary";
import { ruleParts } from "../lib/rule";
import { statusOf } from "../lib/status";
import { useLoads, type Requests } from "../lib/useLoads";

/** One page of history: the API's maximum (D13). */
export const HISTORY_LIMIT = 200;

interface CheckSlots {
  project: Project;
  check: CheckDetail;
  history: HistoryPage;
  runs: RunPage;
}

interface Older {
  generation: number;
  items: HistoryEntry[];
  cursor: string | null;
  busy: boolean;
  failure: ApiFailure | null;
}

function Identity({ check }: { check: CheckDetail }): ReactElement {
  return (
    <section className="panel check-identity" aria-labelledby="check-heading">
      <h1 id="check-heading" className="check-title">
        {check.name}
      </h1>
      {check.expression !== check.name && <code className="check__expression check-expression">{check.expression}</code>}
      <dl className="facts facts--wide">
        <div>
          <dt>Dataset</dt> <dd>{check.dataset}</dd>
        </div>
        <div>
          <dt>Datasource</dt> <dd>{check.datasource}</dd>
        </div>
        <div>
          <dt>Owner</dt> <dd>{check.owner ?? <span className="quiet">none</span>}</dd>
        </div>
        <div>
          <dt>Tags</dt>{" "}
          <dd>
            {check.tags.length === 0 ? (
              <span className="quiet">none</span>
            ) : (
              <ul className="tags">
                {check.tags.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        <div>
          <dt>Source</dt>{" "}
          <dd>
            <code>{check.source}</code>
          </dd>
        </div>
        <div>
          <dt>Id</dt>{" "}
          <dd>
            <code>{check.id}</code>
          </dd>
        </div>
      </dl>
    </section>
  );
}

function RuleSection({
  check,
  project,
  pending,
  now,
}: {
  check: CheckDetail;
  project: Project | null;
  pending: boolean;
  now: number;
}): ReactElement {
  return (
    <section className="panel" aria-labelledby="rule-heading">
      <h2 id="rule-heading" className="panel__title">
        Rule
      </h2>
      <dl className="rule">
        {ruleParts(check.rule).map((p) => (
          <div key={p.role} data-role={p.role}>
            <dt>{p.label}</dt>{" "}
            <dd>
              <code>{p.condition.text}</code>
            </dd>
          </div>
        ))}
      </dl>
      <p className="caption">
        The current rule, from the check files
        {project !== null && (
          <>
            {" "}
            loaded <Ago iso={project.loaded_at} now={now} />
          </>
        )}
        .
      </p>
      {pending && (
        <p className="pending-note" data-note="pending-rule">
          No run has used this rule yet. The results below were judged by an earlier rule.
        </p>
      )}
    </section>
  );
}

function LatestSection({
  check,
  newestRunId,
  judgedBy,
  now,
}: {
  check: CheckDetail;
  newestRunId: string | null;
  judgedBy: string | null;
  now: number;
}): ReactElement {
  return (
    <section className="panel latest-result" aria-labelledby="latest-heading">
      <h2 id="latest-heading" className="panel__title">
        Latest result
      </h2>
      <div className="latest-result__body">
        <StatusBadge status={statusOf(check)} />
        <Result latest={check.latest} now={now} />
        <When latest={check.latest} newestRunId={newestRunId} now={now} />
      </div>
      {judgedBy !== null && (
        <p className="pending-note" data-note="judged-by">
          Judged by an earlier rule, <code>{judgedBy}</code>. The check files now say{" "}
          <code>{check.expression}</code>, and no run has used that yet.
        </p>
      )}
    </section>
  );
}

function NotFoundPanel({ id, projectBroken }: { id: string; projectBroken: boolean }): ReactElement {
  return (
    <section className="panel" aria-labelledby="check-heading">
      <h1 id="check-heading" className="check-title">
        Check not found
      </h1>
      <p>
        No check with the id <code>{id}</code> is loaded, and no results are recorded for it.
      </p>
      {projectBroken && (
        <p className="quiet">Some check files did not load, so the check may be in one of them. See the overview.</p>
      )}
      <p>
        <a href="/">Go to the overview</a>
      </p>
    </section>
  );
}

export function CheckPage({ id }: { id: string }): ReactElement {
  const requests = useMemo<Requests<CheckSlots>>(
    () => ({
      project: getProject,
      check: () => getCheck(id),
      history: () => getHistory(id, HISTORY_LIMIT),
      runs: () => listRuns(1),
    }),
    [id],
  );
  const { slots, busy, now, generation, reload, capture } = useLoads(requests);
  const { project, check, history, runs } = slots;
  const [olderState, setOlder] = useState<Older | null>(null);
  // Older pages belong to the round that fetched them; a refresh drops them (D14).
  const older = olderState !== null && olderState.generation === generation ? olderState : null;

  const loadedProject = project.state === "ok" ? project.data : null;
  const loadedCheck = check.state === "ok" ? check.data : null;
  const checkMissing = check.state === "failed" && isNotFound(check.failure);
  const firstPage = history.state === "ok" ? history.data : null;
  const entries = useMemo(
    () => (firstPage === null ? [] : [...firstPage.items, ...(older?.items ?? [])]),
    [firstPage, older],
  );
  const cursor = older !== null ? older.cursor : (firstPage?.next_cursor ?? null);
  const newestRunId = runs.state === "ok" ? (runs.data.items[0]?.id ?? null) : null;

  const newest = entries[0];
  const pending = loadedCheck !== null && newest !== undefined && newest.expression !== loadedCheck.expression;

  const name = loadedCheck?.name ?? (checkMissing ? (newest?.name ?? null) : null);
  useEffect(() => {
    document.title = `${name ?? (checkMissing && history.state === "failed" ? "Check not found" : "Check")} · tablewatch`;
  }, [name, checkMissing, history.state]);

  const loadOlder = (): void => {
    if (cursor === null) return;
    const current = capture();
    const round = generation;
    const base = older?.items ?? [];
    setOlder({ generation: round, items: base, cursor, busy: true, failure: null });
    getHistory(id, HISTORY_LIMIT, cursor).then(
      (page) => {
        if (current()) {
          setOlder({ generation: round, items: [...base, ...page.items], cursor: page.next_cursor, busy: false, failure: null });
        }
      },
      (error: unknown) => {
        if (current()) setOlder({ generation: round, items: base, cursor, busy: false, failure: failureOf(error) });
      },
    );
  };

  const model = useMemo(() => {
    if (entries.length === 0) return null;
    return layoutChart({
      entries,
      check:
        loadedCheck === null
          ? null
          : { metric: loadedCheck.metric, unit: loadedCheck.unit, expression: loadedCheck.expression },
      rule: loadedCheck?.rule ?? null,
      streak:
        loadedCheck?.latest != null
          ? { outcome: loadedCheck.latest.outcome, since: loadedCheck.latest.since, latestAt: loadedCheck.latest.started_at }
          : null,
    });
  }, [entries, loadedCheck]);

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || (check.state === "failed" && !checkMissing) || history.state === "failed")
    status = "Could not load everything.";
  else status = "Up to date.";

  // What the page can say about the check.
  const notLoadedButRecorded = checkMissing && firstPage !== null && entries.length > 0;
  const unknown = checkMissing && history.state === "failed" && isNotFound(history.failure);

  let historyBody: ReactElement | null = null;
  if (loadedCheck !== null || notLoadedButRecorded) {
    if (history.state === "loading") historyBody = <p className="loading">Loading…</p>;
    else if (history.state === "failed")
      historyBody = <LoadError what="the history" failure={history.failure} onRetry={reload} />;
    else if (entries.length === 0) historyBody = <p className="empty">No results recorded yet.</p>;
    else {
      const summary =
        model === null
          ? ""
          : chartSummary({
              entries,
              series: model.series,
              rule: loadedCheck?.rule ?? null,
              pending,
              more: cursor !== null,
            });
      const chartable = model !== null && model.series.axisMetric !== null;
      historyBody = (
        <>
          {chartable ? (
            <HistoryFigure
              model={model}
              title={`History of ${name ?? id}`}
              summary={summary}
              rule={loadedCheck?.rule ?? null}
              pending={pending}
              partialCount={cursor !== null ? entries.length : null}
            />
          ) : (
            <p className="caption" data-caption="not-charted">
              These results measured different metrics, so they are not charted. The table lists every one.
            </p>
          )}
          <HistoryTable
            entries={entries}
            current={
              loadedCheck === null
                ? null
                : { expression: loadedCheck.expression, dataset: loadedCheck.dataset, metric: loadedCheck.metric }
            }
            now={now}
          />
          {older?.failure != null && <LoadError what="older results" failure={older.failure} onRetry={loadOlder} />}
          {cursor !== null && (
            <p>
              <button type="button" className="button" onClick={loadOlder} aria-busy={older?.busy ?? false} disabled={older?.busy ?? false}>
                Load older results
              </button>
            </p>
          )}
        </>
      );
    }
  }

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
            <Identity check={loadedCheck} />
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

        {historyBody !== null && (
          <section className="panel history" aria-labelledby="history-heading">
            <h2 id="history-heading" className="panel__title">
              History
            </h2>
            {historyBody}
          </section>
        )}
      </main>
    </>
  );
}
