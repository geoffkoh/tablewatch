import type { ReactElement, ReactNode } from "react";
import type { CheckSummary, Project } from "../api/types";
import { countStatuses, errorsLastFailing, type Status } from "../lib/status";
import { PROBLEMS_ID } from "./ProjectProblems";
import { StatusIcon } from "./StatusIcon";

function IncompleteMarker(): ReactElement {
  return (
    <a
      className="incomplete"
      href={`#${PROBLEMS_ID}`}
      title="Some checks did not load: see the check file errors above"
    >
      incomplete
    </a>
  );
}

interface TileProps {
  status: Status;
  count: number;
  label: string;
  note?: ReactNode;
  incomplete?: boolean;
}

function Tile({ status, count, label, note, incomplete = false }: TileProps): ReactElement {
  return (
    <li className={`tile status--${status}`} data-status={status}>
      <span className="tile__head">
        <StatusIcon status={status} /> <span className="tile__count">{count}</span>{" "}
        <span className="tile__label">{label}</span>
        {incomplete && (
          <>
            {" "}
            <IncompleteMarker />
          </>
        )}
      </span>
      {note !== undefined && (
        <>
          {" "}
          <span className="tile__note">{note}</span>
        </>
      )}
    </li>
  );
}

/**
 * Every loaded check's latest result (D3). This is not the latest run's
 * counts: the caption names the scope, and the latest-run panel names its own.
 */
export function Summary({ project, checks }: { project: Project; checks: readonly CheckSummary[] }): ReactElement {
  const counts = countStatuses(checks);
  const incomplete = !project.ok;
  const wereFailing = errorsLastFailing(checks);
  const allClear = project.ok && counts.total > 0 && counts.pass === counts.total;
  const n = counts.total;

  return (
    <section className="panel summary" aria-labelledby="summary-heading">
      <h2 id="summary-heading" className="panel__title">
        Summary
      </h2>
      <p className="caption">
        Latest result of each of the {n} {n === 1 ? "check" : "checks"} loaded
        {incomplete && (
          <>
            {" "}
            (<IncompleteMarker />)
          </>
        )}
      </p>
      {allClear && <p className="all-clear">All checks passing</p>}
      {n === 0 && <p className="caption">No checks are loaded, so there is nothing to report.</p>}
      <ul className="tiles">
        <Tile status="fail" count={counts.fail} label="failing" incomplete={incomplete} />
        <Tile
          status="error"
          count={counts.error}
          label={counts.error === 1 ? "error" : "errors"}
          note={
            <>
              could not evaluate
              {wereFailing > 0 && `; ${String(wereFailing)} ${wereFailing === 1 ? "was" : "were"} failing`}
            </>
          }
        />
        <Tile status="warn" count={counts.warn} label={counts.warn === 1 ? "warning" : "warnings"} />
        <Tile status="none" count={counts.none} label="no result" note="state unknown" />
        {counts.skipped > 0 && <Tile status="skipped" count={counts.skipped} label="skipped" />}
        <Tile status="pass" count={counts.pass} label="passing" incomplete={incomplete} />
      </ul>
    </section>
  );
}
