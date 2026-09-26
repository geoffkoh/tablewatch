/**
 * The chart with its title, key and captions (spec 004 D7, D11, D13, D20).
 * Captions are HTML, under the chart: rule changes with both recorded
 * expressions, values left off the axis, a rule no run has used yet, and
 * whether older results exist.
 */
import type { ReactElement } from "react";
import type { HistoryEntry, Rule } from "../../api/types";
import { unitLabel } from "../../lib/chart/format";
import type { ChartModel } from "../../lib/chart/layout";
import { legendItems } from "../../lib/chart/legend";
import type { RuleChange } from "../../lib/chart/series";
import { ruleSentence } from "../../lib/rule";
import { absolute } from "../../lib/time";
import { ChartKey } from "./ChartKey";
import { HistoryChart } from "./HistoryChart";

function RunTime({ entry }: { entry: HistoryEntry }): ReactElement {
  return <time dateTime={entry.started_at}>{absolute(entry.started_at)}</time>;
}

function ChangeCaption({ change, numbered }: { change: RuleChange; numbered: boolean }): ReactElement {
  return (
    <li data-rule-change={change.number}>
      {numbered ? `Rule change ${String(change.number)}: between runs ` : "Rule changed between runs "}
      <RunTime entry={change.older} /> and <RunTime entry={change.newer} />
      {change.expressionChanged && (
        <>
          : from <code>{change.older.expression}</code> to <code>{change.newer.expression}</code>
        </>
      )}
      {change.datasetChanged && (
        <>
          {change.expressionChanged ? "; dataset" : ": dataset"} from <code>{change.older.dataset}</code> to{" "}
          <code>{change.newer.dataset}</code>
        </>
      )}
      .
    </li>
  );
}

interface HistoryFigureProps {
  model: ChartModel;
  title: string;
  summary: string;
  /** The loaded rule; null for a check no longer loaded. */
  rule: Rule | null;
  /** The newest result was judged by another rule: an edit not yet run. */
  pending: boolean;
  /** How many results are loaded, when older ones exist; otherwise null. */
  partialCount: number | null;
}

export function HistoryFigure({ model, title, summary, rule, pending, partialCount }: HistoryFigureProps): ReactElement {
  const { series } = model;
  const changes = series.ruleChanges;
  const k = series.offAxis.length;
  return (
    <figure className="chart">
      <p className="chart__axis-title">
        {series.axisMetric ?? "value"} ({unitLabel(series.axisUnit)})
      </p>
      {rule !== null && (
        <p className="chart__rule">
          Current rule: <code>{ruleSentence(rule)}</code>
        </p>
      )}
      <ChartKey items={legendItems(model)} />
      <HistoryChart model={model} title={title} summary={summary} />
      <figcaption className="chart__captions">
        <ul>
          {pending && rule !== null && (
            <li data-caption="pending">
              No run has used the current rule yet, so no threshold is drawn. Every result here was judged by an
              earlier rule.
            </li>
          )}
          {rule === null && (
            <li data-caption="not-loaded">This check is not in the loaded check files, so no rule is drawn.</li>
          )}
          {changes.map((c) => (
            <ChangeCaption key={c.number} change={c} numbered={changes.length > 1} />
          ))}
          {k > 0 && (
            <li data-caption="other-metric">
              {k === 1 ? "1 result" : `${String(k)} results`} measured a different metric (
              {series.otherMetrics.join(", ")}) and {k === 1 ? "is" : "are"} not plotted. The table lists{" "}
              {k === 1 ? "it" : "them"}.
            </li>
          )}
          {partialCount !== null && (
            <li data-caption="partial">
              Shows the latest {partialCount} results, not all of them.
            </li>
          )}
        </ul>
      </figcaption>
    </figure>
  );
}
