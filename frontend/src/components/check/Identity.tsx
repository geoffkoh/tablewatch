import type { ReactElement } from "react";
import type { CheckDetail } from "../../api/types";

/** What the check is: its name, expression, dataset, owner, tags, file and id. */
export function Identity({ check }: { check: CheckDetail }): ReactElement {
  return (
    <section className="panel check-identity" aria-labelledby="check-heading">
      <h1 id="check-heading" className="check-title">
        {check.name}
      </h1>
      {check.expression !== check.name && <code className="check__expression check-expression">{check.expression}</code>}
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
          <dt>Source</dt>{" "}
          <dd>
            <code>{check.source}</code>
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
