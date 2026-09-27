/**
 * A check's latest result and its age, in the words both pages use (spec 003
 * O2/O4/O5, spec 004 D4). The overview's rows and the check page import
 * these; there is no second copy of the wording.
 */
import type { ReactElement } from "react";
import type { LastEvaluated, LatestResult } from "../api/types";
import { SINCE_PREFIX, STATUS_META } from "../lib/status";
import { Ago } from "./Time";

export function LastEvaluatedNote({ last, now }: { last: LastEvaluated; now: number }): ReactElement {
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

/** The value and message; for an error, "Could not evaluate" and never the "—". */
export function Result({ latest, now }: { latest: LatestResult | null; now: number }): ReactElement {
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
      {latest.message !== null && latest.message !== "" && <span className="result__message">{latest.message}</span>}
    </span>
  );
}

interface WhenProps {
  latest: LatestResult | null;
  newestRunId: string | null;
  now: number;
}

/** The age, the streak ("Failing since …") and "Not in the latest run". */
export function When({ latest, newestRunId, now }: WhenProps): ReactElement | null {
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
