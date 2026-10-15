/**
 * "Changed recently" (spec 042 K-D2): the 5 newest state changes from
 * `GET /alerts?limit=5`, worded exactly as the Alerts page (`lib/alerts.ts`),
 * with "All alerts" linking to `/alerts`. None recorded reads "No state
 * changes recorded yet."
 */
import type { ReactElement } from "react";
import type { ApiFailure } from "../../api/api";
import type { Alert, AlertPage } from "../../api/types";
import { RetiredBadge } from "../RetiredBadge";
import { StatusIcon } from "../StatusIcon";
import { Ago } from "../Time";
import { alertEventStatus, alertEventText, previousText } from "../../lib/alerts";
import { checkHref } from "../../lib/route";
import { PanelError } from "./PanelError";

function ChangedRow({ alert, now }: { alert: Alert; now: number }): ReactElement {
  const previous = previousText(alert.previous_outcome);
  return (
    <li className="dashboard-changed__row" data-event={alert.event} data-check-id={alert.check.id}>
      <StatusIcon status={alertEventStatus(alert.event)} />
      <span className="dashboard-changed__event">{alertEventText(alert.event)}</span>
      <a href={checkHref(alert.check.id)}>{alert.check.name}</a>
      {alert.check.state === "retired" && (
        <>
          {" "}
          <RetiredBadge />
        </>
      )}
      {previous !== null && <span className="quiet"> {previous}</span>}
      <Ago iso={alert.started_at} now={now} />
    </li>
  );
}

export function ChangedPanel({
  alerts,
  failure,
  now,
  onRetry,
}: {
  alerts: AlertPage | null;
  failure: ApiFailure | null;
  now: number;
  onRetry: () => void;
}): ReactElement {
  return (
    <section className="panel dashboard-panel" aria-labelledby="changed-heading">
      <h2 id="changed-heading" className="panel__title">
        Changed recently
      </h2>
      {failure !== null && <PanelError what="recent changes" onRetry={onRetry} />}
      {failure === null && alerts !== null && (
        <>
          {alerts.items.length === 0 ? (
            <p className="empty">No state changes recorded yet.</p>
          ) : (
            <ul className="dashboard-changed" aria-label="Changed recently">
              {alerts.items.map((alert) => (
                <ChangedRow key={`${alert.run_id}\u0000${alert.check.id}`} alert={alert} now={now} />
              ))}
            </ul>
          )}
          <p className="panel__link">
            <a href="/alerts">All alerts</a>
          </p>
        </>
      )}
    </section>
  );
}
