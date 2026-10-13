import type { ReactElement } from "react";
import type { RetiredCheckSummary } from "../../api/types";
import { Marked } from "../Marked";
import { RetiredBadge } from "../RetiredBadge";
import { Since } from "../Time";

/**
 * A retired check's header (spec 037 S13): the "Retired" badge, when it
 * retired, and the file it was last defined in — `last_known_location`,
 * omitted for a check that never ran (D3, D7) — then the facts its last
 * result still carries. No Source row (no file any more) and no rule.
 */
export function RetiredIdentity({ check, now }: { check: RetiredCheckSummary; now: number }): ReactElement {
  return (
    <section className="panel check-identity" aria-labelledby="check-heading">
      <h1 id="check-heading" className="check-title">
        {check.name}
        <RetiredBadge />
      </h1>
      {check.expression !== null && check.expression !== check.name && (
        <code className="check__expression check-expression">
          <Marked text={check.expression} />
        </code>
      )}
      <p className="pending-note" data-note="retired">
        <Since iso={check.retired_since} now={now} prefix="Retired since" />
        {check.last_known_location !== null && (
          <>
            {" "}
            — last defined in{" "}
            <code>
              <Marked text={check.last_known_location} />
            </code>
          </>
        )}
      </p>
      <dl className="facts facts--wide">
        <div>
          <dt>Dataset</dt> <dd>{check.dataset}</dd>
        </div>
        <div>
          <dt>Datasource</dt> <dd>{check.datasource}</dd>
        </div>
        <div>
          <dt>Owner</dt> <dd>{check.owner ?? <span className="quiet">none</span>}</dd>
        </div>
        <div>
          <dt>Tags</dt>{" "}
          <dd>
            {check.tags.length === 0 ? (
              <span className="quiet">none</span>
            ) : (
              <ul className="tags">
                {check.tags.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        <div>
          <dt>Id</dt>{" "}
          <dd>
            <code>{check.id}</code>
          </dd>
        </div>
      </dl>
    </section>
  );
}
