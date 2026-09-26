import type { ReactElement } from "react";
import type { CheckSummary, LastEvaluated, LatestResult } from "../api/types";
import { sortProblemsFirst, STATUS_META, statusOf } from "../lib/status";
import { StatusBadge } from "./StatusIcon";
import { Ago } from "./Time";

/** Words for a streak. "since", never "continuously": runs happen at intervals (O5). */
const SINCE_PREFIX: Readonly<Record<LatestResult["outcome"], string | null>> = {
  fail: "Failing since",
  warn: "Warning since",
  error: "Could not evaluate since",
  skipped: "Skipped since",
  pass: null,
};

function LastEvaluatedNote({ last, now }: { last: LastEvaluated; now: number }): ReactElement {
  const since = SINCE_PREFIX[last.outcome];
  return (
    <span className="last-evaluated">
      Last evaluated: <span className={`inline-status status--${last.outcome}`}>{STATUS_META[last.outcome].label}</span>,{" "}
      <Ago iso={last.started_at} now={now} />
      {since !== null && (
        <>
          ; <Ago iso={last.since} now={now} prefix={since.toLowerCase()} />
        </>
      )}
    </span>
  );
}

function Result({ latest, now }: { latest: LatestResult | null; now: number }): ReactElement {
  if (latest === null) {
    return (
      <span className="result result--none">
        <span className="result__headline">No result recorded</span>
        <span className="quiet">Its state is unknown.</span>
      </span>
    );
  }
  if (latest.outcome === "error") {
    // display_value is "—" on an error: it is not a measured value, so it is not shown.
    return (
      <span className="result result--error">
        <span className="result__headline">Could not evaluate</span>
        <span className="result__message">{latest.message ?? "No message was recorded."}</span>
        {latest.last_evaluated !== null && <LastEvaluatedNote last={latest.last_evaluated} now={now} />}
      </span>
    );
  }
  if (latest.outcome === "skipped") {
    return (
      <span className="result">
        <span className="result__headline">Skipped</span>
        {latest.message !== null && <span className="result__message">{latest.message}</span>}
        {latest.last_evaluated !== null && <LastEvaluatedNote last={latest.last_evaluated} now={now} />}
      </span>
    );
  }
  return (
    <span className="result">
      <span className="result__value">{latest.display_value}</span>
      {latest.message !== null && latest.message !== "" && (
        <span className="result__message">{latest.message}</span>
      )}
    </span>
  );
}

function When({ latest, newestRunId, now }: { latest: LatestResult | null; newestRunId: string | null; now: number }): ReactElement | null {
  if (latest === null) return null;
  const since = SINCE_PREFIX[latest.outcome];
  return (
    <span className="when">
      <Ago iso={latest.started_at} now={now} />
      {since !== null && (
        <span className={`since status-text--${latest.outcome}`}>
          <Ago iso={latest.since} now={now} prefix={since} />
        </span>
      )}
      {newestRunId !== null && latest.run_id !== newestRunId && (
        <span className="quiet not-in-latest">Not in the latest run</span>
      )}
    </span>
  );
}

function Row({ check, newestRunId, now }: { check: CheckSummary; newestRunId: string | null; now: number }): ReactElement {
  const status = statusOf(check);
  return (
    <tr className={`check-row row--${status}`} data-check-id={check.id} data-status={status}>
      <td className="cell-status">
        <StatusBadge status={status} />
      </td>
      <td className="cell-check">
        <span className="check__name">{check.name}</span>
        {check.expression !== check.name && <code className="check__expression">{check.expression}</code>}
        <span className="check__where">
          <span className="check__dataset">{check.dataset}</span>
          <span className="check__source">{check.source}</span>
        </span>
      </td>
      <td className="cell-result">
        <Result latest={check.latest} now={now} />
      </td>
      <td className="cell-when">
        <When latest={check.latest} newestRunId={newestRunId} now={now} />
      </td>
    </tr>
  );
}

interface CheckTableProps {
  checks: readonly CheckSummary[];
  newestRunId: string | null;
  now: number;
}

/** Every loaded check, problems first (O1). */
export function CheckTable({ checks, newestRunId, now }: CheckTableProps): ReactElement {
  const rows = sortProblemsFirst(checks);
  return (
    <section className="panel checks" aria-labelledby="checks-heading">
      <h2 id="checks-heading" className="panel__title">
        Checks, problems first
      </h2>
      {rows.length === 0 ? (
        <p className="empty">No checks are loaded.</p>
      ) : (
        <div className="table-scroll">
          <table className="check-table">
            <caption className="visually-hidden">
              Every loaded check with its latest result: failing first, then errors, warnings, no
              result, skipped, and passing.
            </caption>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Check</th>
                <th scope="col">Latest result</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((check) => (
                <Row key={check.id} check={check} newestRunId={newestRunId} now={now} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
