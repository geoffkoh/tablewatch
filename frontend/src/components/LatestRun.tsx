import type { ReactElement } from "react";
import type { Run } from "../api/types";
import { selectionParts } from "../lib/selection";
import { StatusBadge } from "./StatusIcon";
import { Ago } from "./Time";

const OUTCOME_SENTENCE: Readonly<Record<Run["outcome"], string>> = {
  fail: "The data failed at least one check.",
  error: "tablewatch could not evaluate one or more of its checks.",
  warn: "At least one check warned; none failed.",
  pass: "Every check it ran passed.",
  skipped: "Its checks were skipped.",
};

function Selection({ run }: { run: Run }): ReactElement {
  const parts = selectionParts(run.selection);
  if (parts.length === 0) return <>all checks</>;
  return (
    <ul className="selection">
      {parts.map((p) => (
        <li key={p.key}>
          <span className="selection__key">{p.label}:</span>{" "}
          {p.values.length > 0 ? p.values.join(", ") : "(none)"}
        </li>
      ))}
    </ul>
  );
}

interface LatestRunProps {
  run: Run | null;
  now: number;
  /** Checks the run counted that are not loaded now (spec 017 P3). */
  notLoaded: number;
  /** The project loaded cleanly; then nothing was dropped by a broken file. */
  projectOk: boolean;
}

function NotLoaded({ k, projectOk }: { k: number; projectOk: boolean }): ReactElement {
  const one = k === 1;
  return (
    <p className="quiet run-counts__not-loaded">
      {k} of them {one ? "is" : "are"} not loaded now.
      {projectOk && ` ${one ? "It was" : "They were"} edited or removed since the run.`}
    </p>
  );
}

/** The newest run (O8). Its counts are only what that run selected. */
export function LatestRun({ run, now, notLoaded, projectOk }: LatestRunProps): ReactElement {
  return (
    <section className="panel latest-run" aria-labelledby="run-heading">
      <h2 id="run-heading" className="panel__title">
        Latest run
      </h2>
      {run === null ? (
        <p className="empty">
          No runs are recorded for this project yet. Run <code>tablewatch run</code> to record the
          first results.
        </p>
      ) : (
        <>
          <dl className="facts">
            <div>
              <dt>Started</dt>{" "}
              <dd>
                <Ago iso={run.started_at} now={now} />
                {run.finished_at === null && <span className="quiet"> (did not finish)</span>}
              </dd>
            </div>
            <div>
              <dt>Trigger</dt>{" "}
              <dd>{run.trigger}</dd>
            </div>
            <div>
              <dt>Outcome</dt>{" "}
              <dd>
                <StatusBadge status={run.outcome} /> <span className="quiet">{OUTCOME_SENTENCE[run.outcome]}</span>
              </dd>
            </div>
            <div>
              <dt>Selected</dt>{" "}
              <dd>
                <Selection run={run} />
              </dd>
            </div>
          </dl>
          <p className="caption run-counts__caption">
            This run: {run.counts.total} {run.counts.total === 1 ? "check" : "checks"}
          </p>
          {notLoaded > 0 && <NotLoaded k={notLoaded} projectOk={projectOk} />}
          <ul className="run-counts" aria-label="This run's results">
            <li>{run.counts.pass} pass</li>
            <li>{run.counts.warn} warn</li>
            <li>{run.counts.fail} fail</li>
            <li>{run.counts.error} error</li>
            {run.counts.skipped > 0 && <li>{run.counts.skipped} skipped</li>}
          </ul>
        </>
      )}
    </section>
  );
}
