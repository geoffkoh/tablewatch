/**
 * A check's definition history (spec 038 S8): what each version changed, so
 * Priya can tell whether a failing check's rule moved or the data did. Shown
 * on an active, disabled or retired check's page — unlike SQL and Source, it
 * is kept in the results store, not read from the check files, so it has
 * something to say for a retired check too.
 */
import type { ReactElement } from "react";
import { isNotFound } from "../../api/api";
import type { Definition, DefinitionClause, DefinitionList } from "../../api/types";
import { diffDefinition, renderClause, type ClauseChange } from "../../lib/definitionDiff";
import type { Load } from "../../lib/useLoads";
import { LoadError } from "../LoadError";
import { Ago } from "../Time";

/** Versions newer than this many stay open; older ones are behind "Show more" (compactness, S8). */
export const VISIBLE_VERSIONS = 3;

const CHANGE_LABEL: Readonly<Record<ClauseChange["kind"], string>> = {
  added: "Added",
  removed: "Removed",
  changed: "Changed",
};

function ClauseList({ clauses }: { clauses: readonly DefinitionClause[] }): ReactElement {
  if (clauses.length === 0) return <p className="quiet">No clauses.</p>;
  return (
    <ul className="definition__clauses">
      {clauses.map((c) => (
        <li key={c.key}>
          <code className="definition__key">{c.key}</code>: <code>{renderClause(c)}</code>
        </li>
      ))}
    </ul>
  );
}

function ChangeItem({ change }: { change: ClauseChange }): ReactElement {
  return (
    <li data-change={change.kind}>
      <span className="definition__flag">{CHANGE_LABEL[change.kind]}</span> <code className="definition__key">{change.key}</code>
      {change.kind === "changed" && change.before !== null && change.after !== null && (
        <>
          : <code>{renderClause(change.before)}</code> → <code>{renderClause(change.after)}</code>
        </>
      )}
      {change.kind === "added" && change.after !== null && (
        <>
          : <code>{renderClause(change.after)}</code>
        </>
      )}
      {change.kind === "removed" && change.before !== null && (
        <>
          : <code>{renderClause(change.before)}</code>
        </>
      )}
    </li>
  );
}

function RunOf({ definition }: { definition: Definition }): ReactElement {
  if (definition.run_id === null) return <>recorded by sync</>;
  return (
    <>
      from run <code>{definition.run_id}</code>
    </>
  );
}

function VersionItem({ definition, previous, now }: { definition: Definition; previous: Definition | null; now: number }): ReactElement {
  const changes = diffDefinition(previous, definition);
  return (
    <li className="definition__version" data-version={definition.version}>
      <p className="definition__meta">
        <strong>Version {definition.version}</strong>, <Ago iso={definition.recorded_at} now={now} />,{" "}
        <RunOf definition={definition} />.
      </p>
      {previous === null ? (
        <ClauseList clauses={definition.clauses} />
      ) : changes.length === 0 ? (
        <p className="quiet">No visible clause change.</p>
      ) : (
        <ul className="definition__changes">
          {changes.map((c) => (
            <ChangeItem key={c.key} change={c} />
          ))}
        </ul>
      )}
    </li>
  );
}

function DefinitionBody({ items, now }: { items: readonly Definition[]; now: number }): ReactElement {
  if (items.length === 0) return <p className="empty">No definition recorded yet.</p>;
  const visible = items.slice(0, VISIBLE_VERSIONS);
  const rest = items.slice(VISIBLE_VERSIONS);
  return (
    <>
      <ul className="definition__versions">
        {visible.map((d, i) => (
          <VersionItem key={d.version} definition={d} previous={items[i + 1] ?? null} now={now} />
        ))}
      </ul>
      {rest.length > 0 && (
        <details className="notice definition__older">
          <summary>{rest.length === 1 ? "1 earlier version" : `${String(rest.length)} earlier versions`}</summary>
          <ul className="definition__versions">
            {rest.map((d, i) => (
              <VersionItem key={d.version} definition={d} previous={items[visible.length + i + 1] ?? null} now={now} />
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

export function DefinitionSection({
  definitions,
  checkMissing,
  now,
  onRetry,
}: {
  definitions: Load<DefinitionList>;
  /** `/checks/{id}` is 404: no row exists at all, so a 404 here is expected, not a failure. */
  checkMissing: boolean;
  now: number;
  onRetry: () => void;
}): ReactElement {
  let body: ReactElement;
  if (definitions.state === "loading") body = <p className="loading">Loading…</p>;
  else if (definitions.state === "failed") {
    body = checkMissing && isNotFound(definitions.failure) ? (
      <p data-definition-note="not-loaded">
        No definitions are recorded: this check is not in the loaded check files or the results store.
      </p>
    ) : (
      <LoadError what="the definition history" failure={definitions.failure} onRetry={onRetry} level={3} scope="section" />
    );
  } else body = <DefinitionBody items={definitions.data.items} now={now} />;

  return (
    <section className="panel definition" aria-labelledby="definition-heading">
      <h2 id="definition-heading" className="panel__title">
        Definition
      </h2>
      {body}
    </section>
  );
}
