/**
 * The check explorer, `/checks` (spec 015): the `checks/` tree with problem
 * counts on every folder and file, a text search and a status filter. Loads
 * `/project` and `/checks` through the shared hook; filtering runs in memory
 * and never fetches (E18).
 *
 * The search and the statuses live in the URL (`?q=…&status=…`). Each change
 * rewrites the current history entry with `replaceState` (decision 1): no
 * entry is added and nothing navigates, so spec 004 D7 still holds, and Back
 * from a check's page returns to the same view.
 */
import { useDeferredValue, useEffect, useId, useMemo, useState, type ReactElement } from "react";
import { getProject, listChecks } from "../api/api";
import type { CheckList, CheckSummary, Project } from "../api/types";
import { ExplorerTree } from "../components/ExplorerTree";
import { Header } from "../components/Header";
import { LoadError } from "../components/LoadError";
import { ProjectProblems } from "../components/ProjectProblems";
import {
  buildTree,
  commonFolder,
  explorerSearch,
  filterChecks,
  isFiltering,
  matchesText,
  MAX_QUERY_LENGTH,
  orderStatuses,
  parseExplorerQuery,
  type ExplorerQuery,
} from "../lib/explorer";
import { EXPLORER_HREF } from "../lib/route";
import { countStatuses, STATUS_META, STATUS_ORDER, type Status } from "../lib/status";
import { useLoads, type Requests } from "../lib/useLoads";

interface ExplorerSlots {
  project: Project;
  checks: CheckList;
}

const REQUESTS: Requests<ExplorerSlots> = {
  project: getProject,
  checks: () => listChecks(),
};

/** One toggle per status present, or selected, with its count among the checks the search matches (E9). */
function StatusFilter({
  checks,
  query,
  onChange,
}: {
  checks: readonly CheckSummary[];
  query: ExplorerQuery;
  onChange: (statuses: Status[]) => void;
}): ReactElement {
  const present = new Set(checks.map((c) => (c.latest === null ? "none" : c.latest.outcome)));
  const counts = countStatuses(checks.filter((c) => matchesText(c, query.q)));
  const selected = new Set(query.statuses);
  const shown = STATUS_ORDER.filter((s) => present.has(s) || selected.has(s));
  return (
    <fieldset className="status-filter">
      <legend className="status-filter__legend">Status</legend>
      {shown.map((status) => {
        const checked = selected.has(status);
        return (
          <label key={status} className={`status-toggle status--${status}`}>
            <input
              type="checkbox"
              checked={checked}
              onChange={() => {
                const next = new Set(selected);
                if (checked) next.delete(status);
                else next.add(status);
                onChange(orderStatuses(next));
              }}
            />
            <span className="status-toggle__label">{STATUS_META[status].label}</span>{" "}
            <span className="status-toggle__count">{counts[status]}</span>
          </label>
        );
      })}
    </fieldset>
  );
}

function plural(n: number): string {
  return `${String(n)} ${n === 1 ? "check" : "checks"}`;
}

export function Explorer({ path, search }: { path: string; search: string }): ReactElement {
  const { slots, busy, now, reload } = useLoads(REQUESTS);
  const { project, checks } = slots;
  const loadedProject = project.state === "ok" ? project.data : null;
  const [query, setQuery] = useState<ExplorerQuery>(() => parseExplorerQuery(search));
  // Typing stays responsive on a large tree: the tree follows a deferred copy (decision 2).
  const shownQuery = useDeferredValue(query);
  const searchId = useId();
  const hintId = useId();

  useEffect(() => {
    document.title = "Checks · tablewatch";
  }, []);

  // Keep the URL in step, without a new history entry (decision 1).
  useEffect(() => {
    const next = explorerSearch(query);
    if (next !== window.location.search) window.history.replaceState(window.history.state, "", `${path}${next}${window.location.hash}`);
  }, [query, path]);

  const items = checks.state === "ok" ? checks.data.items : null;
  const root = useMemo(() => (items === null ? [] : commonFolder(items.map((c) => c.location.file))), [items]);
  const filtered = useMemo(() => (items === null ? [] : filterChecks(items, shownQuery)), [items, shownQuery]);
  const tree = useMemo(() => buildTree(filtered, root), [filtered, root]);
  const filtering = isFiltering(shownQuery);

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || checks.state === "failed") status = "Could not load everything.";
  else status = "Up to date.";

  return (
    <>
      <Header project={loadedProject} now={now} busy={busy} onRefresh={reload} projectIsHeading={false} />
      <main id="main" className="page" tabIndex={-1} aria-busy={busy}>
        <p className="visually-hidden" role="status">
          {status}
        </p>
        <p className="back">
          <a href="/">Overview</a>
        </p>
        <h1 className="check-title">Checks</h1>
        {project.state === "failed" && <LoadError what="the project" failure={project.failure} onRetry={reload} />}
        {loadedProject !== null && <ProjectProblems project={loadedProject} />}
        {checks.state === "loading" && <p className="loading">Loading…</p>}
        {checks.state === "failed" && <LoadError what="the checks" failure={checks.failure} onRetry={reload} />}
        {items !== null && items.length === 0 && (
          <section className="panel explorer">
            <p className="empty">No checks are loaded.</p>
          </section>
        )}
        {items !== null && items.length > 0 && (
          <section className="panel explorer" aria-label="Check files">
            <form
              className="explorer__controls"
              role="search"
              onSubmit={(event) => {
                event.preventDefault();
              }}
            >
              <div className="explorer__search">
                <label htmlFor={searchId}>Search checks</label>
                <input
                  id={searchId}
                  type="search"
                  className="explorer__input"
                  value={query.q}
                  maxLength={MAX_QUERY_LENGTH}
                  aria-describedby={hintId}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => {
                    const q = event.target.value.slice(0, MAX_QUERY_LENGTH);
                    setQuery((prev) => ({ ...prev, q }));
                  }}
                />
                <span id={hintId} className="quiet explorer__hint">
                  Name, expression, dataset, file or id
                </span>
              </div>
              <StatusFilter
                checks={items}
                query={query}
                onChange={(statuses) => {
                  setQuery((prev) => ({ ...prev, statuses }));
                }}
              />
            </form>
            <p className="explorer__showing" aria-live="polite">
              {filtering
                ? `Showing ${String(filtered.length)} of ${plural(items.length)}.`
                : `Showing all ${plural(items.length)}.`}
            </p>
            {filtered.length === 0 ? (
              <div className="explorer__none">
                <p className="empty">No checks match.</p>
                <p>
                  <a href={EXPLORER_HREF}>Clear search and filters</a>
                </p>
              </div>
            ) : (
              <ExplorerTree key={filtering ? "filtering" : "all"} root={tree} filtering={filtering} />
            )}
          </section>
        )}
      </main>
    </>
  );
}
