/**
 * "Check changes" (spec 042 K-D4): the 5 newest changes from
 * `GET /check-changes?limit=5` — added, a definition redefined, disabled,
 * retired or enabled again. None recorded reads "No changes to checks
 * recorded yet."
 */
import type { ReactElement } from "react";
import type { ApiFailure } from "../../api/api";
import type { CheckChange, CheckChangeList } from "../../api/types";
import { checkChangeText } from "../../lib/checkChanges";
import { checkHref } from "../../lib/route";
import { RetiredBadge } from "../RetiredBadge";
import { Ago } from "../Time";
import { PanelError } from "./PanelError";

function ChangeRow({ change, now }: { change: CheckChange; now: number }): ReactElement {
  return (
    <li className="dashboard-changes__row" data-kind={change.kind} data-check-id={change.check.id}>
      <span className="dashboard-changes__kind">{checkChangeText(change)}</span>
      <a href={checkHref(change.check.id)}>{change.check.name}</a>
      {change.check.state === "retired" && (
        <>
          {" "}
          <RetiredBadge />
        </>
      )}
      <Ago iso={change.at} now={now} />
    </li>
  );
}

export function ChangesPanel({
  changes,
  failure,
  now,
  onRetry,
}: {
  changes: CheckChangeList | null;
  failure: ApiFailure | null;
  now: number;
  onRetry: () => void;
}): ReactElement {
  return (
    <section className="panel dashboard-panel" aria-labelledby="changes-heading">
      <h2 id="changes-heading" className="panel__title">
        Check changes
      </h2>
      {failure !== null && <PanelError what="check changes" onRetry={onRetry} />}
      {failure === null && changes !== null && (
        <>
          {changes.items.length === 0 ? (
            <p className="empty">No changes to checks recorded yet.</p>
          ) : (
            <ul className="dashboard-changes" aria-label="Check changes">
              {changes.items.map((change, i) => (
                <ChangeRow key={`${change.check.id}\u0000${String(i)}`} change={change} now={now} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
