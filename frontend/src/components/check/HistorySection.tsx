import { useMemo, type ReactElement } from "react";
import type { CheckDetail, HistoryPage } from "../../api/types";
import { layoutChart } from "../../lib/chart/layout";
import { chartSummary } from "../../lib/chart/summary";
import type { Load } from "../../lib/useLoads";
import { HistoryFigure } from "../chart/HistoryFigure";
import { HistoryTable } from "../HistoryTable";
import { LoadError } from "../LoadError";
import type { OlderHistory } from "./useOlderHistory";

/**
 * The check's history: the chart (when every result measured one metric), the
 * table, and "Load older results". `check` is null when the check is no longer
 * loaded but has recorded results.
 */
export function HistorySection({
  id,
  name,
  check,
  history,
  older,
  pending,
  now,
  onRetry,
}: {
  id: string;
  name: string | null;
  check: CheckDetail | null;
  history: Load<HistoryPage>;
  older: OlderHistory;
  pending: boolean;
  now: number;
  onRetry: () => void;
}): ReactElement {
  const { entries, cursor } = older;

  const model = useMemo(() => {
    if (entries.length === 0) return null;
    return layoutChart({
      entries,
      check: check === null ? null : { metric: check.metric, unit: check.unit, expression: check.expression },
      rule: check?.rule ?? null,
      streak:
        check?.latest != null
          ? { outcome: check.latest.outcome, since: check.latest.since, latestAt: check.latest.started_at }
          : null,
    });
  }, [entries, check]);

  let body: ReactElement;
  if (history.state === "loading") body = <p className="loading">Loading…</p>;
  else if (history.state === "failed") body = <LoadError what="the history" failure={history.failure} onRetry={onRetry} />;
  else if (entries.length === 0) body = <p className="empty">No results recorded yet.</p>;
  else {
    const summary =
      model === null
        ? ""
        : chartSummary({
            entries,
            series: model.series,
            rule: check?.rule ?? null,
            pending,
            more: cursor !== null,
          });
    const chartable = model !== null && model.series.axisMetric !== null;
    body = (
      <>
        {chartable ? (
          <HistoryFigure
            model={model}
            title={`History of ${name ?? id}`}
            summary={summary}
            rule={check?.rule ?? null}
            pending={pending}
            partialCount={cursor !== null ? entries.length : null}
          />
        ) : (
          <p className="caption" data-caption="not-charted">
            These results measured different metrics, so they are not charted. The table lists every one.
          </p>
        )}
        <HistoryTable
          entries={entries}
          current={check === null ? null : { expression: check.expression, dataset: check.dataset, metric: check.metric }}
          now={now}
        />
        {older.failure !== null && <LoadError what="older results" failure={older.failure} onRetry={older.loadOlder} />}
        {cursor !== null && (
          <p>
            <button
              type="button"
              className="button"
              onClick={older.loadOlder}
              aria-busy={older.loading}
              disabled={!older.canLoadOlder}
            >
              Load older results
            </button>
          </p>
        )}
      </>
    );
  }

  return (
    <section className="panel history" aria-labelledby="history-heading">
      <h2 id="history-heading" className="panel__title">
        History
      </h2>
      {body}
    </section>
  );
}
