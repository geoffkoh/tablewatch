import type { ReactElement } from "react";
import type { CheckSummary } from "../api/types";
import { checkHref, EXPLORER_HREF } from "../lib/route";
import { sortProblemsFirst, statusOf } from "../lib/status";
import { Result, When } from "./LatestResult";
import { StatusBadge } from "./StatusIcon";

function Row({ check, newestRunId, now }: { check: CheckSummary; newestRunId: string | null; now: number }): ReactElement {
  const status = statusOf(check);
  return (
    <tr className={`check-row row--${status}`} data-check-id={check.id} data-status={status}>
      <td className="cell-status">
        <StatusBadge status={status} />
      </td>
      <td className="cell-check">
        <a className="check__name" href={checkHref(check.id)}>
          {check.name}
        </a>
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
      <div className="panel__head">
        <h2 id="checks-heading" className="panel__title">
          Checks, problems first
        </h2>
        <a className="panel__link" href={EXPLORER_HREF}>
          Browse all checks
        </a>
      </div>
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
