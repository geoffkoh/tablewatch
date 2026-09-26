/**
 * Every loaded result, newest first (spec 004 D12). It is also the chart's
 * accessible alternative: one row per result, including those the chart
 * draws in a lane or leaves off its axis.
 */
import type { ReactElement } from "react";
import type { HistoryEntry } from "../api/types";
import { zoneName, localTime, parseTimestamp } from "../lib/time";
import { StatusBadge } from "./StatusIcon";
import { Ago } from "./Time";

function Value({ entry }: { entry: HistoryEntry }): ReactElement {
  // display_value is "—" when nothing was measured; words say why instead.
  if (entry.outcome === "error") return <span className="result__headline">Could not evaluate</span>;
  if (entry.value === null) return <span className="quiet">No value measured</span>;
  return <span className="result__value">{entry.display_value}</span>;
}

interface HistoryTableProps {
  entries: readonly HistoryEntry[];
  /** The loaded check's expression and dataset; null for a check no longer loaded. */
  current: { expression: string; dataset: string; metric: string } | null;
  now: number;
}

export function HistoryTable({ entries, current, now }: HistoryTableProps): ReactElement {
  const newest = entries[0];
  const expression = current?.expression ?? newest?.expression ?? "";
  const dataset = current?.dataset ?? newest?.dataset ?? "";
  const zone = zoneName(newest === undefined ? Date.now() : parseTimestamp(newest.started_at));
  return (
    <div className="table-scroll">
      <table className="check-table history-table">
        <caption className="history-table__caption">
          Every loaded result, newest first. Times in {zone}.
        </caption>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Outcome</th>
            <th scope="col">Value</th>
            <th scope="col">Message</th>
            <th scope="col">Rule</th>
            <th scope="col">Trigger</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, index) => {
            const otherRule = entry.expression !== expression;
            const otherDataset = entry.dataset !== dataset;
            const otherMetric = current !== null && entry.metric !== current.metric && entry.value !== null;
            return (
              <tr
                key={`${entry.run_id}-${String(index)}`}
                className={`history-row row--${entry.outcome}`}
                data-run-id={entry.run_id}
                data-outcome={entry.outcome}
                data-index={index}
              >
                <td className="cell-when">
                  <span className="when">
                    <span>{localTime(entry.started_at)}</span>
                    <Ago iso={entry.started_at} now={now} />
                  </span>
                </td>
                <td>
                  <StatusBadge status={entry.outcome} />
                </td>
                <td>
                  <Value entry={entry} />
                  {otherMetric && <span className="quiet history-table__note">Not on the chart: measured by {entry.metric}</span>}
                </td>
                <td className="result__message">{entry.message ?? ""}</td>
                <td>
                  {otherRule && (
                    <span className="history-table__rule" data-other-rule="true">
                      <span className="history-table__flag">Different rule</span> <code>{entry.expression}</code>
                    </span>
                  )}
                  {otherDataset && (
                    <span className="history-table__rule" data-other-dataset="true">
                      <span className="history-table__flag">Other dataset</span> <code>{entry.dataset}</code>
                    </span>
                  )}
                  {!otherRule && !otherDataset && (
                    <span className="quiet">{current === null ? "Same as the newest" : "Current"}</span>
                  )}
                </td>
                <td>{entry.trigger}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
