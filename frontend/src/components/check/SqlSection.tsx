import { useRef, type ReactElement } from "react";
import { isNotFound } from "../../api/api";
import type { CheckSql, QueryStatement, ScanStatement, Statement, Unit } from "../../api/types";
import type { Load } from "../../lib/useLoads";
import { CodeBlock } from "../CodeBlock";
import { CopyButton } from "../CopyButton";
import { LoadError } from "../LoadError";
import { Marked } from "../Marked";

/**
 * The SQL a run of the check's dataset sends (spec 005). Compiled from the
 * check files as loaded, never "the query behind this result": results do not
 * store their SQL (P1, P5). The section is always open, so `#sql`, find in
 * page and the tests reach it.
 */
export function SqlSection({
  sql,
  unit,
  checkMissing,
  onRetry,
}: {
  sql: Load<CheckSql>;
  /** The check's unit from `/checks/{id}`; null when that has not answered (P10, P13). */
  unit: Unit | null;
  /** `/checks/{id}` answered 404: a 404 from `/sql` then means "no longer loaded" (P6). */
  checkMissing: boolean;
  onRetry: () => void;
}): ReactElement {
  let body: ReactElement;
  if (sql.state === "loading") body = <p className="loading">Loading…</p>;
  else if (sql.state === "failed")
    body =
      checkMissing && isNotFound(sql.failure) ? (
        <p data-sql-note="not-loaded">SQL is not available: this check is not in the loaded check files.</p>
      ) : (
        <LoadError what="the SQL" failure={sql.failure} onRetry={onRetry} level={3} scope="section" />
      );
  else body = <SqlBody sql={sql.data} unit={unit} />;

  return (
    <section id="sql" className="panel sql" aria-labelledby="sql-heading">
      <h2 id="sql-heading" className="panel__title">
        SQL
      </h2>
      {body}
    </section>
  );
}

/** The kinds this page knows; any other kind is skipped (P15, architect A4). */
function isKnown(statement: Statement): statement is ScanStatement | QueryStatement {
  const kind: string = statement.kind;
  return kind === "scan" || kind === "query";
}

function count(n: number, one: string, many: string): string {
  return `${String(n)} ${n === 1 ? one : many}`;
}

/** P10: what the database returns and what tablewatch computes from it. */
function computedNote(unit: Unit | null): string | null {
  if (unit === "percent") return "The database returns counts; tablewatch computes the percentage from them.";
  if (unit === "duration")
    return "The database returns a timestamp; tablewatch computes how long ago it was at the time of each run, so the same data looks older the later the run.";
  return null;
}

function SqlBody({ sql, unit }: { sql: CheckSql; unit: Unit | null }): ReactElement {
  if (sql.error !== null) {
    return (
      <div className="sql__cannot">
        <p>
          <strong>Cannot compile</strong>
        </p>
        <CodeBlock text={sql.error} label="Why the SQL cannot be compiled" tone="error" />
      </div>
    );
  }
  const statements = sql.statements.filter(isKnown);
  const hasScan = statements.some((s) => s.kind === "scan");
  const note = statements.length > 0 ? computedNote(unit) : null;
  return (
    <>
      {statements.map((s, i) =>
        s.kind === "scan" ? <Scan key={i} scan={s} sql={sql} /> : <Query key={i} query={s} sql={sql} />,
      )}
      {sql.schema_lookup && (
        <p data-sql-note="schema-lookup">
          This check reads the list of columns in <code>{sql.dataset}</code> and their types from the database.
          {sql.statements.length === 0 && " It reads no rows, so it has no SQL."}
        </p>
      )}
      {sql.statements.length === 0 && !sql.schema_lookup && <p>This check sends no statement of its own.</p>}
      {note !== null && <p data-sql-note="computed">{note}</p>}
      {statements.length > 0 && (
        <p className="caption" data-sql-note="as-loaded">
          Built from the check files as loaded
          {hasScan && (
            <>
              , for a run of every check on <code>{sql.dataset}</code>
            </>
          )}
          . Results do not store their SQL; a result recorded before these files were loaded may have used different
          SQL.
        </p>
      )}
    </>
  );
}

function Where({ sql }: { sql: CheckSql }): ReactElement {
  return (
    <>
      <code>{sql.dataset}</code> on <code>{sql.datasource}</code>
      {sql.dialect !== null && <> ({sql.dialect})</>}
    </>
  );
}

function Scan({ scan, sql }: { scan: ScanStatement; sql: CheckSql }): ReactElement {
  const block = useRef<HTMLPreElement>(null);
  const text = `${scan.sql};`;
  return (
    <div className="sql__statement" data-kind="scan">
      <p>
        When tablewatch checks <Where sql={sql} />, it reads the table once with this statement. That one read
        computes {count(scan.measures, "value", "values")},{" "}
        {scan.shared_by === 0 ? "for this check only" : `for this check and ${count(scan.shared_by, "other", "others")}`}.
        {scan.uses.length > 0 && " This check uses:"}
      </p>
      {scan.uses.length > 0 && (
        <ul className="sql__uses">
          {scan.uses.map((u) => (
            <li key={u.label}>
              <code>{u.label}</code>{" "}
              <code>
                <Marked text={u.sql} />
              </code>
              {u.shared_by > 0 && <>, also used by {count(u.shared_by, "other check", "other checks")}</>}
            </li>
          ))}
        </ul>
      )}
      <CodeBlock ref={block} text={text} label={`The scan, ${sql.dialect ?? "SQL"}`} />
      <p className="sql__actions">
        <CopyButton text={text} name="the scan" target={block} />
      </p>
    </div>
  );
}

function Query({ query, sql }: { query: QueryStatement; sql: CheckSql }): ReactElement {
  const block = useRef<HTMLPreElement>(null);
  const text = `${query.sql};`;
  return (
    <div className="sql__statement" data-kind="query">
      <p>
        This check sends its own statement to <Where sql={sql} />.
        {query.shared_by > 0 &&
          ` ${count(query.shared_by, "other check uses", "other checks use")} the same statement.`}
      </p>
      <CodeBlock ref={block} text={text} label={`The query, ${sql.dialect ?? "SQL"}`} />
      <p className="sql__actions">
        <CopyButton text={text} name="the query" target={block} />
      </p>
    </div>
  );
}
