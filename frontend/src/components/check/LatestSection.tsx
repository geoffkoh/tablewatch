import type { ReactElement } from "react";
import type { LatestResult as LatestResultType } from "../../api/types";
import { statusOf } from "../../lib/status";
import { Result, When } from "../LatestResult";
import { StatusBadge } from "../StatusIcon";

/**
 * The latest result in the overview's words, and which rule judged it.
 * `check` takes only `latest` and `expression`: a `CheckDetail` (active or
 * disabled) or a retired check's summary (spec 037 S13), whose `expression`
 * may be null (D3) — never read unless `judgedBy` is set, which is only true
 * for a loaded check.
 */
export function LatestSection({
  check,
  newestRunId,
  judgedBy,
  now,
}: {
  check: { latest: LatestResultType | null; expression: string | null };
  newestRunId: string | null;
  /** The earlier expression that judged the latest result, when the files have changed since. */
  judgedBy: string | null;
  now: number;
}): ReactElement {
  return (
    <section className="panel latest-result" aria-labelledby="latest-heading">
      <h2 id="latest-heading" className="panel__title">
        Latest result
      </h2>
      <div className="latest-result__body">
        <StatusBadge status={statusOf(check)} />
        <Result latest={check.latest} now={now} />
        <When latest={check.latest} newestRunId={newestRunId} now={now} />
      </div>
      {judgedBy !== null && check.expression !== null && (
        <p className="pending-note" data-note="judged-by">
          Judged by an earlier rule, <code>{judgedBy}</code>. The check files now say{" "}
          <code>{check.expression}</code>, and no run has used that yet.
        </p>
      )}
    </section>
  );
}
