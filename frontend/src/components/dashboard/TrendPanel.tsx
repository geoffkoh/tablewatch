/**
 * "Problems per run" (spec 042 K-D1): the last 30 runs, oldest left, one bar
 * per run of its `fail + error` count, coloured by the run's own outcome.
 * Each bar's accessible name/tooltip gives the exact counts
 * ("Run of 14 Oct 02:00: 3 failing, 1 in error, 40 passing"); there is no
 * link (Runs is I-15). Under 2 runs reads "Not enough runs to show a trend
 * yet." Reuses the chart's own mark tokens (`--tw-*-mark`), never new colours.
 */
import { useId, type ReactElement } from "react";
import type { ApiFailure } from "../../api/api";
import type { RunPage } from "../../api/types";
import { buildTrendBars, hasTrend, layoutTrendBars } from "../../lib/trend";
import { PanelError } from "./PanelError";

const WIDTH = 320;
const HEIGHT = 72;
const GAP = 4;
const GAP_HALF = GAP / 2;

function TrendChart({ runs }: { runs: RunPage }): ReactElement {
  const bars = buildTrendBars(runs.items);
  const titleId = useId();
  const descId = useId();
  if (!hasTrend(runs.items)) return <p className="empty">Not enough runs to show a trend yet.</p>;
  const laid = layoutTrendBars(bars, WIDTH, HEIGHT);
  return (
    <svg
      className="dashboard-trend"
      viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
      // A group, not an image: an image hides its children from screen
      // readers, and each bar's label is the chart's content (K-D1).
      role="group"
      aria-labelledby={`${titleId} ${descId}`}
      focusable="false"
    >
      <title id={titleId}>Problems per run</title>
      <desc id={descId}>{`The last ${String(bars.length)} runs, oldest to newest.`}</desc>
      {laid.map((bar) => (
        <g
          key={bar.key}
          className={`dashboard-trend__bar dashboard-trend__bar--${bar.outcome}`}
          data-outcome={bar.outcome}
          tabIndex={0}
          role="img"
          aria-label={bar.label}
        >
          <title>{bar.label}</title>
          <rect className="dashboard-trend__hit" x={bar.x - GAP_HALF} y="0" width={bar.width + GAP} height={HEIGHT} />
          <rect x={bar.x} y={bar.y} width={bar.width} height={bar.height} />
        </g>
      ))}
    </svg>
  );
}

export function TrendPanel({
  runs,
  failure,
  onRetry,
}: {
  runs: RunPage | null;
  failure: ApiFailure | null;
  onRetry: () => void;
}): ReactElement {
  return (
    <section className="panel dashboard-panel" aria-labelledby="trend-heading">
      <h2 id="trend-heading" className="panel__title">
        Problems per run
      </h2>
      {failure !== null && <PanelError what="the trend" onRetry={onRetry} />}
      {failure === null && runs !== null && <TrendChart runs={runs} />}
    </section>
  );
}
