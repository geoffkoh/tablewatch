/**
 * The Datasets page, `/datasets` (spec 039 P-D6): one row per
 * (datasource, dataset) built in the browser from every active and disabled
 * check (`listChecks()`, the server's default), with the worst status over
 * its enabled checks, counts, when it was last scanned, its owners and its
 * tags. A search box narrows by dataset, datasource, owner or tag, kept in
 * the URL like the explorer's (`?q=`, decision 1 of spec 015).
 */
import { useEffect, useId, useMemo, useState, type ReactElement } from "react";
import { getProject, listChecks } from "../api/api";
import type { CheckList, CheckSummary, Project } from "../api/types";
import { AppShell } from "../components/AppShell";
import { DisabledBadge } from "../components/DisabledBadge";
import { LoadError } from "../components/LoadError";
import { StatusBadge } from "../components/StatusIcon";
import { Ago } from "../components/Time";
import {
  buildDatasets,
  datasetCountsText,
  filterDatasets,
  hasProblems,
  sortDatasets,
  type DatasetRow,
} from "../lib/datasets";
import { cutQuery, EMPTY_QUERY, explorerSearch, isRetired, MAX_QUERY_LENGTH } from "../lib/explorer";
import { fetchNavProblems, NAV_BACKGROUND } from "../lib/navProblems";
import { EXPLORER_HREF } from "../lib/route";
import { useLoads, type Requests } from "../lib/useLoads";

interface DatasetsSlots {
  project: Project;
  checks: CheckList;
  problems: CheckList;
}

// `listChecks()` with no arguments: the server's default, active and
// disabled checks (never retired — a retired check has no file to read a
// dataset from). `problems` feeds the nav's Checks badge only (P-D3, N3).
const REQUESTS: Requests<DatasetsSlots> = {
  project: getProject,
  checks: () => listChecks(),
  problems: fetchNavProblems,
};

function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}

/** The explorer link a Datasets row's name sets (P-D7): both `datasource` and `dataset`. */
function datasetHref(datasource: string, dataset: string): string {
  return `${EXPLORER_HREF}${explorerSearch({ ...EMPTY_QUERY, datasource: [datasource], dataset: [dataset] })}`;
}

export function Datasets({ path, search }: { path: string; search: string }): ReactElement {
  const { slots, busy, now, reload } = useLoads(REQUESTS, NAV_BACKGROUND);
  const { project, checks, problems } = slots;
  const loadedProject = project.state === "ok" ? project.data : null;
  const [q, setQ] = useState<string>(() => cutQuery(new URLSearchParams(search).get("q") ?? ""));
  const searchId = useId();

  useEffect(() => {
    document.title = `Datasets — ${loadedProject?.name ?? "tablewatch"}`;
  }, [loadedProject]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (q.trim() !== "") params.set("q", cutQuery(q));
    const next = params.toString() === "" ? "" : `?${params.toString()}`;
    if (next !== window.location.search) window.history.replaceState(window.history.state, "", `${path}${next}${window.location.hash}`);
  }, [q, path]);

  // `listChecks()` never returns a retired check (no `state`), but the
  // response type is shared with the explorer's, so this narrows it (as
  // `Overview`'s `loadedChecks` does for the same reason).
  const items = useMemo(
    () => (checks.state === "ok" ? checks.data.items.filter((c): c is CheckSummary => !isRetired(c)) : null),
    [checks],
  );
  const rows = useMemo(() => (items === null ? [] : sortDatasets(buildDatasets(items))), [items]);
  const shown = useMemo(() => filterDatasets(rows, q), [rows, q]);
  const problemCount = rows.filter(hasProblems).length;

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || checks.state === "failed") status = "Could not load everything.";
  else status = "Up to date.";

  return (
    <AppShell
      current="datasets"
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
        <a href="/">Overview</a>
      </p>
      <h1 className="check-title">Datasets</h1>
      {project.state === "failed" && <LoadError what="the project" failure={project.failure} onRetry={reload} />}
      {checks.state === "loading" && <p className="loading">Loading…</p>}
      {checks.state === "failed" && <LoadError what="the datasets" failure={checks.failure} onRetry={reload} />}
      {items !== null && items.length === 0 && (
        <section className="panel">
          <p className="empty">No datasets yet.</p>
        </section>
      )}
      {items !== null && items.length > 0 && (
        <section className="panel datasets" aria-label="Datasets">
          <form
            className="explorer__controls"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
            }}
          >
            <div className="explorer__search">
              <label htmlFor={searchId}>Search datasets</label>
              <input
                id={searchId}
                type="search"
                className="explorer__input"
                value={q}
                maxLength={MAX_QUERY_LENGTH}
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => {
                  setQ(cutQuery(event.target.value));
                }}
              />
            </div>
          </form>
          <p className="caption">
            {plural(rows.length, "dataset")}, {plural(problemCount, "with problem")}
          </p>
          {shown.length === 0 ? (
            <p className="empty">No datasets match.</p>
          ) : (
            <div className="table-scroll">
              <table className="check-table">
                <caption className="visually-hidden">Datasets, problems first</caption>
                <thead>
                  <tr>
                    <th scope="col">Dataset</th>
                    <th scope="col">Datasource</th>
                    <th scope="col">Status</th>
                    <th scope="col">Checks</th>
                    <th scope="col">Last scanned</th>
                    <th scope="col">Owner</th>
                    <th scope="col">Tags</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((row) => (
                    <DatasetRowView key={`${row.datasource}\u0000${row.dataset}`} row={row} now={now} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </AppShell>
  );
}

function DatasetRowView({ row, now }: { row: DatasetRow; now: number }): ReactElement {
  return (
    <tr data-dataset={row.dataset} data-datasource={row.datasource} data-status={row.status}>
      <th scope="row">
        <a href={datasetHref(row.datasource, row.dataset)}>{row.dataset}</a>
      </th>
      <td>{row.datasource}</td>
      <td>{row.status === "disabled" ? <DisabledBadge /> : <StatusBadge status={row.status} />}</td>
      <td>{datasetCountsText(row.counts)}</td>
      <td>{row.lastScanned === null ? "Never" : <Ago iso={row.lastScanned} now={now} />}</td>
      <td>{row.owners.length === 0 ? "—" : row.owners.join(", ")}</td>
      <td>{row.tags.length === 0 ? "—" : row.tags.join(", ")}</td>
    </tr>
  );
}
