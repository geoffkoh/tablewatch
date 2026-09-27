import { useRef, type ReactElement } from "react";
import { isNotFound } from "../../api/api";
import type { CheckSource, FileFilter } from "../../api/types";
import type { Load } from "../../lib/useLoads";
import { CopyButton } from "../CopyButton";
import { LoadError } from "../LoadError";
import { Marked } from "../Marked";
import { SourceBlock } from "../SourceBlock";
import { Ago } from "../Time";

/**
 * The check's own lines in its file, as loaded when the server started (spec
 * 006). Below the SQL, always open, `id="source"`. Its words never claim a
 * result (P5): the lines are today's files, a recorded result may be older.
 */
export function SourceSection({
  source,
  metric,
  checkMissing,
  now,
  onRetry,
}: {
  source: Load<CheckSource>;
  /** The check's metric from `/checks/{id}`; null when that has not answered (P13). */
  metric: string | null;
  /** `/checks/{id}` answered 404: a 404 from `/source` then means "no longer loaded" (P6). */
  checkMissing: boolean;
  now: number;
  onRetry: () => void;
}): ReactElement {
  let body: ReactElement;
  if (source.state === "loading") body = <p className="loading">Loading…</p>;
  else if (source.state === "failed")
    body =
      checkMissing && isNotFound(source.failure) ? (
        <p data-source-note="not-loaded">The source is not available: this check is not in the loaded check files.</p>
      ) : (
        <LoadError what="the source" failure={source.failure} onRetry={onRetry} level={3} scope="section" />
      );
  else body = <SourceBody source={source.data} metric={metric} now={now} />;

  return (
    <section id="source" className="panel source" aria-labelledby="source-heading">
      <h2 id="source-heading" className="panel__title">
        Source
      </h2>
      {body}
    </section>
  );
}

function Path({ path }: { path: string }): ReactElement {
  return (
    <code className="source__path">
      <Marked text={path} />
    </code>
  );
}

function SourceBody({ source, metric, now }: { source: CheckSource; metric: string | null; now: number }): ReactElement {
  const code = useRef<HTMLElement>(null);
  const { text, start_line: start, end_line: end } = source;
  const lines =
    text === null || start === null || end === null ? (
      <p data-source-note="unavailable">
        The lines of this check could not be shown; it is in <Path path={source.path} />.
      </p>
    ) : (
      <>
        <SourceBlock text={text} start={start} label="The check's lines" codeRef={code} />
        <p className="source__actions">
          <CopyButton text={text} name="the source" target={code} />
        </p>
        <p className="caption" data-source-note="as-loaded">
          <Path path={source.path} />, {start === end ? `line ${String(start)}` : `lines ${String(start)}–${String(end)}`}
          , from the check files as loaded <Ago iso={source.loaded_at} now={now} />.
        </p>
      </>
    );
  return (
    <>
      {lines}
      {source.filter !== null && <FilterNote filter={source.filter} metric={metric} />}
      <p data-source-note="defaults">
        The dataset, datasource, owner and tags shown at the top of the page come from this file's first lines
        or a <code>_defaults.yml</code>.
      </p>
    </>
  );
}

/** P13: which rows the check looks at, keyed on `applies`. */
function FilterNote({ filter, metric }: { filter: FileFilter; metric: string | null }): ReactElement {
  const line = `(line ${String(filter.line)})`;
  if (filter.applies)
    return (
      <p data-source-note="filter">
        Only rows matching this file's{" "}
        <code>
          filter: <Marked text={filter.text} />
        </code>{" "}
        {line} are checked.
      </p>
    );
  return (
    <p data-source-note="filter">
      This file's <code>filter:</code> {line} does not apply to this check.
      {metric === "sql_metric" && " Its query runs exactly as written."}
    </p>
  );
}
