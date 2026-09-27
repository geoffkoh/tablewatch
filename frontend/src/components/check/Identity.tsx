import type { ReactElement } from "react";
import type { CheckDetail } from "../../api/types";
import { Marked } from "../Marked";

/**
 * What the check is: its name, expression, dataset, owner, tags, file and id.
 * The file's `file:line:col` links to the Source section whenever that section
 * is on the page (spec 006, P11).
 */
export function Identity({ check, sourceLinked }: { check: CheckDetail; sourceLinked: boolean }): ReactElement {
  const source = (
    <code>
      <Marked text={check.source} />
    </code>
  );
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
          <dd>{sourceLinked ? <a href="#source">{source}</a> : source}</dd>
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
