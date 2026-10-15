/**
 * The Alerts page, `/alerts` (spec 041 P5): every state change across the
 * project, newest first, with what (if anything) was sent about it. C9's
 * Alerts section, for Sam asking "what changed overnight, and was anyone
 * told?" An alert is exactly a recorded `results.state.transition`
 * (`failing`/`erroring`/`recovered`, P1) — the same event the notifiers
 * already send, so the page and a Slack message never disagree.
 *
 * `GET /api/v1/alerts` pages with a cursor, like the check page's history
 * ("Load more"); the event filter (All, Failing, Erroring, Recovered) is
 * kept in `?event=` and, because it narrows what the server sends rather
 * than what is already loaded (unlike the explorer's filters), changing it
 * reloads the page's own slot and drops any older pages loaded so far.
 */
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { getProject, listAlerts } from "../api/api";
import type { Alert, AlertPage, CheckList, Project } from "../api/types";
import { useOlderAlerts } from "../components/alerts/useOlderAlerts";
import { AppShell } from "../components/AppShell";
import { LoadError } from "../components/LoadError";
import { RetiredBadge } from "../components/RetiredBadge";
import { StatusIcon } from "../components/StatusIcon";
import { Ago } from "../components/Time";
import {
  ALERT_FILTER_LABELS,
  ALERT_FILTERS,
  ALERTS_LIMIT,
  alertEventStatus,
  alertEventText,
  alertsEventParam,
  alertsSearch,
  deliveriesText,
  parseAlertsFilter,
  previousText,
  type AlertFilter,
} from "../lib/alerts";
import { fetchNavProblems, NAV_BACKGROUND } from "../lib/navProblems";
import { checkHref } from "../lib/route";
import { useLoads, type Requests } from "../lib/useLoads";

interface AlertsSlots {
  project: Project;
  alerts: AlertPage;
  problems: CheckList;
}

function EventFilter({ filter, onChange }: { filter: AlertFilter; onChange: (next: AlertFilter) => void }): ReactElement {
  return (
    <fieldset className="status-filter alerts-filter">
      <legend className="status-filter__legend">Event</legend>
      {ALERT_FILTERS.map((value) => (
        <label key={value} className="facet-toggle">
          <input
            type="radio"
            name="alerts-event"
            value={value}
            checked={filter === value}
            onChange={() => {
              onChange(value);
            }}
          />
          <span className="facet-toggle__label">{ALERT_FILTER_LABELS[value]}</span>
        </label>
      ))}
    </fieldset>
  );
}

function DeliveriesList({ deliveries }: { deliveries: Alert["deliveries"] }): ReactElement {
  return (
    <ul className="alert-row__deliveries">
      {deliveriesText(deliveries).map((line, index) => (
        <li key={index}>{line}</li>
      ))}
    </ul>
  );
}

function AlertRow({ alert, now }: { alert: Alert; now: number }): ReactElement {
  const previous = previousText(alert.previous_outcome);
  return (
    <li className="alert-row" data-event={alert.event} data-check-id={alert.check.id}>
      <StatusIcon status={alertEventStatus(alert.event)} />
      <span className="alert-row__event">{alertEventText(alert.event)}</span>
      <span className="alert-row__check">
        <a href={checkHref(alert.check.id)}>{alert.check.name}</a>
        {alert.check.state === "retired" && (
          <>
            {" "}
            <RetiredBadge />
          </>
        )}
        <br />
        <span className="alert-row__where">
          {alert.check.dataset} · {alert.check.datasource}
        </span>
      </span>
      {previous !== null && <span className="alert-row__previous">{previous}</span>}
      <Ago iso={alert.started_at} now={now} />
      <DeliveriesList deliveries={alert.deliveries} />
    </li>
  );
}

export function Alerts({ path, search }: { path: string; search: string }): ReactElement {
  const [filter, setFilter] = useState<AlertFilter>(() => parseAlertsFilter(search));

  const requests = useMemo<Requests<AlertsSlots>>(
    () => ({
      project: getProject,
      alerts: () => listAlerts(ALERTS_LIMIT, alertsEventParam(filter)),
      problems: fetchNavProblems,
    }),
    [filter],
  );
  const { slots, busy, now, generation, reload, capture } = useLoads(requests, NAV_BACKGROUND);
  const { project, alerts, problems } = slots;
  const loadedProject = project.state === "ok" ? project.data : null;

  useEffect(() => {
    document.title = `Alerts — ${loadedProject?.name ?? "tablewatch"}`;
  }, [loadedProject]);

  // The filter is read once from the URL on mount (`useState`'s initialiser);
  // every change after that reloads the `alerts` slot with the new `?event=`
  // and rewrites the URL, without adding a history entry (spec 004 D7).
  const mountedFilter = useRef(false);
  useEffect(() => {
    if (!mountedFilter.current) {
      mountedFilter.current = true;
      return;
    }
    reload();
  }, [filter, reload]);

  useEffect(() => {
    const next = alertsSearch(filter);
    if (next !== window.location.search) {
      window.history.replaceState(window.history.state, "", `${path}${next}${window.location.hash}`);
    }
  }, [filter, path]);

  const firstPage = alerts.state === "ok" ? alerts.data : null;
  const older = useOlderAlerts({ filter, firstPage, busy, generation, capture });
  const { entries, cursor } = older;

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || alerts.state === "failed") status = "Could not load everything.";
  else status = "Up to date.";

  return (
    <AppShell
      current="alerts"
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
      <h1 className="check-title">Alerts</h1>
      {project.state === "failed" && <LoadError what="the project" failure={project.failure} onRetry={reload} />}
      <EventFilter
        filter={filter}
        onChange={(next) => {
          setFilter(next);
        }}
      />
      {alerts.state === "loading" && <p className="loading">Loading…</p>}
      {alerts.state === "failed" && <LoadError what="the alerts" failure={alerts.failure} onRetry={reload} />}
      {alerts.state === "ok" && entries.length === 0 && <p className="empty">No state changes recorded yet.</p>}
      {alerts.state === "ok" && entries.length > 0 && (
        <>
          <ul className="alerts-list" aria-label="Alerts">
            {entries.map((alert) => (
              <AlertRow key={`${alert.run_id}\u0000${alert.check.id}`} alert={alert} now={now} />
            ))}
          </ul>
          {older.failure !== null && (
            <LoadError what="more alerts" failure={older.failure} onRetry={older.loadOlder} level={3} scope="section" />
          )}
          {cursor !== null && (
            <p>
              <button
                type="button"
                className="button"
                onClick={older.loadOlder}
                aria-busy={older.loading}
                disabled={!older.canLoadOlder}
              >
                Load more
              </button>
            </p>
          )}
        </>
      )}
    </AppShell>
  );
}
