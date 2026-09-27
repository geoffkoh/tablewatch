/**
 * The history chart (spec 004 D5–D11, D19, D20). It draws exactly the model
 * `layoutChart` returns; every decision is in `lib/chart/`.
 *
 * Accessibility: the `<svg>` is `role="img"`, named by its `<title>` and
 * described by its `<desc>` (a text summary). The history table below it is
 * the full alternative. Interaction lives on a focusable group around the
 * SVG: hover or arrow keys move a crosshair between results, and a tooltip
 * (value first) shows the time with its zone, the outcome and the message.
 * The same text is announced through a polite live region.
 *
 * Security (decision 14): no link, reference, embedded image or embedded
 * HTML element of any kind (src/test/security.test.tsx lists them); ids come
 * from `useId()`; positions are SVG attributes and transforms, never inline
 * style.
 */
import { useId, useState, type KeyboardEvent, type ReactElement } from "react";
import { tooltipBox, type ChartModel } from "../../lib/chart/layout";
import { StatusShape } from "../shapes";

interface HistoryChartProps {
  model: ChartModel;
  title: string;
  summary: string;
}

const HALF = 6; // half a mark's 12-unit box
const MARK_SCALE = 0.75; // 16-unit shapes drawn at 12 units

export function HistoryChart({ model, title, summary }: HistoryChartProps): ReactElement {
  const id = useId();
  const titleId = `${id}-title`;
  const descId = `${id}-desc`;
  const [active, setActive] = useState<number | null>(null);
  const columns = model.columns;
  const column = active === null ? undefined : columns[active];
  const tip = column === undefined ? null : tooltipBox(model, column);
  const activeKeys = new Set(column?.points.map((p) => String(p.index)) ?? []);
  const { plot } = model;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (columns.length === 0) return;
    const last = columns.length - 1;
    let next: number | null = active;
    if (event.key === "ArrowRight") next = active === null ? last : Math.min(last, active + 1);
    else if (event.key === "ArrowLeft") next = active === null ? last : Math.max(0, active - 1);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else if (event.key === "Escape") next = null;
    else return;
    event.preventDefault();
    setActive(next);
  };

  return (
    <div
      className="chart__interact"
      tabIndex={0}
      role="group"
      aria-label="History chart. Use the left and right arrow keys to read each result."
      onKeyDown={onKeyDown}
      onFocus={() => {
        if (active === null && columns.length > 0) setActive(columns.length - 1);
      }}
      onBlur={() => {
        setActive(null);
      }}
      onPointerLeave={() => {
        setActive(null);
      }}
    >
      <svg
        className="chart__svg"
        viewBox={`0 0 ${String(model.width)} ${String(model.height)}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        focusable="false"
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>{summary}</desc>

        <g className="chart__grid" aria-hidden="true">
          {model.yTicks.map((t) => (
            <line
              key={`g${String(t.value)}`}
              className={t.value === 0 ? "chart__zero" : undefined}
              x1={plot.x0}
              x2={plot.x1}
              y1={t.y}
              y2={t.y}
            />
          ))}
        </g>

        <g className="chart__bands">
          {model.bands.map((b, i) => (
            <rect
              key={`b${String(i)}`}
              className={`chart__band chart__band--${b.severity}`}
              x={b.x0}
              y={b.y0}
              width={Math.max(0, b.x1 - b.x0)}
              height={Math.max(0, b.y1 - b.y0)}
            />
          ))}
          {model.lines.map((l, i) => (
            <line
              key={`l${String(i)}`}
              className={`chart__boundary chart__boundary--${l.severity}`}
              data-value={l.y}
              x1={l.x0}
              x2={l.x1}
              y1={l.y}
              y2={l.y}
            />
          ))}
        </g>

        <g className="chart__axis chart__axis--y">
          {model.yTicks.map((t) => (
            <text key={`y${String(t.value)}`} x={plot.x0 - 8} y={t.y} dy="0.32em" textAnchor="end">
              {t.label}
            </text>
          ))}
        </g>

        {model.lanes.length > 0 && (
          <g className="chart__lanes">
            <line className="chart__lane-rule" x1={plot.x0} x2={plot.x1} y1={plot.y1 + 5} y2={plot.y1 + 5} />
            {model.lanes.map((lane) => (
              <text
                key={lane.lane}
                className="chart__lane-label"
                data-lane={lane.lane}
                x={plot.x0 - 8}
                y={lane.y}
                dy="0.32em"
                textAnchor="end"
              >
                {lane.label}
              </text>
            ))}
          </g>
        )}

        {model.markers.map((m) => (
          <g key={`m${String(m.number)}`} className="chart__marker" data-marker={m.number}>
            <line x1={m.x} x2={m.x} y1={m.y0} y2={m.y1} />
            <text className="chart__label" x={m.labelX} y={m.labelY} dy="0.32em">
              {m.label}
            </text>
          </g>
        ))}

        {model.streak !== null && (
          <g className="chart__streak">
            <path
              d={`M${String(model.streak.x0)} ${String(model.streak.y + 4)}V${String(model.streak.y)}H${String(model.streak.x1)}V${String(model.streak.y + 4)}`}
            />
            <text className="chart__label" x={model.streak.labelX} y={model.streak.labelY - 3} dy="0.32em">
              {model.streak.label}
            </text>
          </g>
        )}

        <g className="chart__series">
          {model.paths.map((d, i) => (
            <path key={`p${String(i)}`} className="chart__line" d={d} />
          ))}
        </g>

        {column !== undefined && (
          <line className="chart__crosshair" x1={column.x} x2={column.x} y1={plot.y0} y2={model.xAxisY} />
        )}

        <g className="chart__marks">
          {model.marks.map((m) => (
            <g
              key={m.key}
              className={`mark mark--${m.outcome}${activeKeys.has(m.key) ? " is-active" : ""}`}
              data-outcome={m.outcome}
              data-lane={m.lane ?? "value"}
              data-index={m.point.index}
              transform={`translate(${String(m.x - HALF)} ${String(m.y - HALF)}) scale(${String(MARK_SCALE)})`}
            >
              <StatusShape status={m.outcome} />
            </g>
          ))}
        </g>

        <g className="chart__right">
          {model.rightLabels.map((l) => (
            <text
              key={l.id}
              className={`chart__label chart__label--${l.kind}`}
              data-label={l.kind}
              x={model.rightX}
              y={l.y}
              dy="0.32em"
            >
              {l.text}
            </text>
          ))}
        </g>

        <g className="chart__axis chart__axis--x">
          <line className="chart__baseline" x1={plot.x0} x2={plot.x1} y1={model.xAxisY} y2={model.xAxisY} />
          {model.xTicks.map((t) => (
            <g key={`x${String(t.x)}`}>
              <line x1={t.x} x2={t.x} y1={model.xAxisY} y2={model.xAxisY + 4} />
              <text x={t.x} y={model.xAxisY + 16} textAnchor="middle">
                {t.label}
              </text>
            </g>
          ))}
          <text className="chart__time-note" x={plot.x1} y={model.xAxisY + 32} textAnchor="end">
            {model.timeNote}
          </text>
        </g>

        <g className="chart__hits">
          {columns.map((c, i) => (
            <rect
              key={c.key}
              className="chart__hit"
              x={c.x0}
              y={plot.y0}
              width={c.x1 - c.x0}
              height={Math.max(0, model.xAxisY - plot.y0)}
              onPointerEnter={() => {
                setActive(i);
              }}
            />
          ))}
        </g>

        {tip !== null && (
          <g className="chart__tooltip" transform={`translate(${String(tip.x)} ${String(tip.y)})`}>
            <rect className="chart__tooltip-box" width={tip.width} height={tip.height} rx="4" />
            {tip.lines.map((line, i) => (
              <text
                key={`t${String(i)}`}
                className={line.strong ? "chart__tooltip-value" : "chart__tooltip-text"}
                x="8"
                y={line.y}
              >
                {line.text}
              </text>
            ))}
          </g>
        )}
      </svg>
      <p className="visually-hidden" aria-live="polite">
        {tip === null ? "" : tip.lines.map((l) => l.text).join(". ")}
      </p>
    </div>
  );
}
