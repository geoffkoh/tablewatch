/**
 * The history chart's geometry, as data (chart requirements 6 and 7). The
 * SVG component draws exactly what this returns and decides nothing. The
 * viewBox has a fixed width; its height grows with the rows the chart needs
 * (marker labels above, lanes below), so nothing is measured in the DOM.
 */
import type { HistoryEntry, Outcome, Rule } from "../../api/types";
import { ruleBoundaries } from "../rule";
import { SINCE_PREFIX, STATUS_META } from "../status";
import { absolute, calendarDay, parseTimestamp, sameLocalDay, timeTick, zoneName } from "../time";
import { bands as bandsFor, type Severity } from "./bands";
import { yAxis, type YAxis } from "./domain";
import { formatThreshold, formatTick } from "./format";
import { assignRows, CHAR_WIDTH, LATEST_GAP, LINE_HEIGHT, stackLabels, textWidth, truncate, type Wanted } from "./labels";
import { linear } from "./scale";
import { buildSeries, type CurrentCheck, type Lane, type Point, type Series } from "./series";
import { timeTicks } from "./ticks";

export const WIDTH = 720;
export const PLOT_HEIGHT = 200;
export const ROW_HEIGHT = 18;
export const LANE_HEIGHT = 22;
/** Marks sit this far inside the plot's left and right edges. */
export const X_INSET = 14;
/**
 * A hover/focus column's width when marks allow it (dataviz: a 24px hit
 * target). Columns never overlap, so marks closer than this get their share.
 */
export const MIN_COLUMN = 24;
/** A mark's box: 12 units, drawn from the 16-unit status shapes. */
export const MARK_SIZE = 12;
const MAX_RIGHT = 168;
const MIN_RIGHT = 48;

export interface Streak {
  outcome: Outcome;
  since: string;
  latestAt: string;
}

export interface ChartInput {
  entries: readonly HistoryEntry[];
  check: CurrentCheck | null;
  rule: Rule | null;
  streak: Streak | null;
}

export interface Rect {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export interface Mark {
  key: string;
  x: number;
  y: number;
  outcome: Outcome;
  lane: Lane | null;
  point: Point;
}

export interface RightLabel {
  id: string;
  kind: "boundary" | "latest" | "off-range";
  text: string;
  y: number;
}

export interface Marker {
  number: number;
  x: number;
  y0: number;
  y1: number;
  label: string;
  labelX: number;
  labelY: number;
}

export interface Column {
  key: string;
  x: number;
  x0: number;
  x1: number;
  points: Point[];
}

export interface ChartModel {
  width: number;
  height: number;
  plot: Rect;
  series: Series;
  axis: YAxis;
  yTicks: { y: number; label: string; value: number }[];
  xTicks: { x: number; label: string }[];
  xAxisY: number;
  timeNote: string;
  bands: (Rect & { severity: Severity })[];
  lines: { x0: number; x1: number; y: number; severity: Severity; text: string }[];
  rightLabels: RightLabel[];
  rightX: number;
  lanes: { lane: Lane; label: string; y: number }[];
  marks: Mark[];
  paths: string[];
  markers: Marker[];
  streak: { x0: number; x1: number; y: number; label: string; labelX: number; labelY: number } | null;
  columns: Column[];
}

export const LANE_LABEL: Readonly<Record<Lane, string>> = {
  error: "Could not evaluate",
  "no-value": "No value",
};

/** What a mark is called in the legend and the tooltip (D9). */
export function markName(point: Pick<Point, "outcome" | "lane">): string {
  if (point.lane === "error") return "Could not evaluate";
  if (point.lane === "no-value") {
    if (point.outcome === "skipped") return "Skipped";
    return `${STATUS_META[point.outcome].label}: no value measured`;
  }
  return STATUS_META[point.outcome].label;
}

/** The tooltip for a column: value first, then outcome, time (with zone) and message. */
export function tooltipLines(points: readonly Point[]): { strong: boolean; text: string }[] {
  const lines: { strong: boolean; text: string }[] = [];
  // Newest first, as in the table.
  for (const p of [...points].sort((a, b) => a.index - b.index)) {
    if (p.kind === "value") {
      lines.push({ strong: true, text: p.entry.display_value });
      lines.push({ strong: false, text: STATUS_META[p.outcome].label });
    } else if (p.kind === "off-axis") {
      lines.push({ strong: true, text: p.entry.display_value });
      lines.push({ strong: false, text: `${STATUS_META[p.outcome].label}; measured by ${p.entry.metric}, not plotted` });
    } else {
      lines.push({ strong: true, text: markName(p) });
    }
    lines.push({ strong: false, text: absolute(p.entry.started_at) });
    if (p.entry.message !== null && p.entry.message !== "") lines.push({ strong: false, text: truncate(p.entry.message, 64) });
  }
  return lines;
}

const round = (v: number): number => Math.round(v * 10) / 10;

export function layoutChart({ entries, check, rule, streak }: ChartInput): ChartModel {
  const series = buildSeries(entries, check);
  const unit = series.axisUnit;
  const drawRule = rule !== null && series.band !== null;
  const boundaries = drawRule ? ruleBoundaries(rule) : [];
  const axis = yAxis(
    series.plotted.map((p) => p.value ?? 0),
    boundaries,
    unit,
  );

  // ---- x (time) ----
  const times = series.points.map((p) => p.t);
  const tMin = times.length > 0 ? Math.min(...times) : 0;
  const tMax = times.length > 0 ? Math.max(...times) : 0;

  // ---- lanes, left margin ----
  const laneList = (["error", "no-value"] as const).filter((l) => series.lanes[l].length > 0);
  const yTickLabels = axis.values.map((v) => formatTick(v, unit, axis.step));
  const left =
    Math.max(28, ...yTickLabels.map((t) => textWidth(t)), ...laneList.map((l) => textWidth(LANE_LABEL[l]))) + 12;

  // ---- right labels (text only; positions after the plot is known) ----
  const newestValue = series.plotted[series.plotted.length - 1];
  const threshold = (v: number): string => formatThreshold(v, unit);
  const bandsResult = drawRule ? bandsFor(rule, [axis.lo, axis.hi], threshold) : { fail: [], warn: [], lines: [] };
  const offRange = drawRule ? axis.offRange : [];
  const rightBudget = Math.floor((MAX_RIGHT - 10) / CHAR_WIDTH);
  const rightTexts: Omit<RightLabel, "y">[] = [
    ...bandsResult.lines.map((l, i) => ({ id: `line-${String(i)}`, kind: "boundary" as const, text: truncate(l.text, rightBudget) })),
    ...(newestValue !== undefined
      ? [{ id: "latest", kind: "latest" as const, text: truncate(newestValue.entry.display_value, rightBudget) }]
      : []),
    ...offRange.map((o, i) => ({
      id: `off-${String(i)}`,
      kind: "off-range" as const,
      text: truncate(`${threshold(o.value)} ${o.side}`, rightBudget),
    })),
  ];
  const right = Math.min(MAX_RIGHT, Math.max(MIN_RIGHT, ...rightTexts.map((t) => textWidth(t.text) + 14)));

  const plotX0 = left;
  const plotX1 = WIDTH - right;
  const xOf =
    tMax > tMin
      ? linear([tMin, tMax], [plotX0 + X_INSET, plotX1 - X_INSET])
      : () => (plotX0 + plotX1) / 2;

  // ---- top rows: the streak, then rule-change labels ----
  const changes = series.ruleChanges;
  const markerLabels = changes.map((c) => ({
    change: c,
    text: changes.length === 1 ? "Rule changed" : `Rule change ${String(c.number)}`,
    x: round(xOf(c.t)),
  }));
  const spans = markerLabels.map((m) => {
    const w = textWidth(m.text);
    const x0 = Math.min(Math.max(m.x - w / 2, 4), WIDTH - 4 - w);
    return { id: String(m.change.number), x0, x1: x0 + w };
  });
  const markerRows = assignRows(spans);
  const markerRowCount = markerLabels.length === 0 ? 0 : Math.max(...[...markerRows.values()]) + 1;

  let streakModel: ChartModel["streak"] = null;
  const streakPrefix = streak === null ? null : SINCE_PREFIX[streak.outcome];
  const streakSince = streak === null ? NaN : parseTimestamp(streak.since);
  const streakLatest = streak === null ? NaN : parseTimestamp(streak.latestAt);
  const showStreak =
    streak !== null && streakPrefix !== null && !Number.isNaN(streakSince) && !Number.isNaN(streakLatest) && times.length > 0;
  const rows = (showStreak ? 1 : 0) + markerRowCount;
  // Headroom above the plot: label rows, or room for a mark on the top gridline.
  const plotY0 = rows > 0 ? 10 + rows * ROW_HEIGHT + 6 : 16;
  const plotY1 = plotY0 + PLOT_HEIGHT;
  const yOf = linear([axis.lo, axis.hi], [plotY1, plotY0]);
  const clampY = (y: number): number => Math.min(Math.max(y, plotY0), plotY1);
  const clampX = (x: number): number => Math.min(Math.max(x, plotX0), plotX1);

  if (showStreak && streak !== null && streakPrefix !== null) {
    const x0 = round(clampX(xOf(Math.max(streakSince, tMin))));
    const x1 = round(clampX(xOf(Math.min(streakLatest, tMax))));
    const label = `${streakPrefix} ${absolute(streak.since)}`;
    const w = textWidth(label);
    const labelX = Math.min(Math.max(x0, 4), WIDTH - 4 - w);
    const y = 10 + ROW_HEIGHT / 2;
    streakModel = { x0, x1: Math.max(x0, x1), y: y + 5, label, labelX, labelY: y };
  }

  const markerTop = 10 + (showStreak ? ROW_HEIGHT : 0);
  const lanesTop = plotY1 + 10;
  const lanesBottom = lanesTop + laneList.length * LANE_HEIGHT;
  const markers: Marker[] = markerLabels.map((m, i) => {
    const row = markerRows.get(String(m.change.number)) ?? 0;
    const span = spans[i] ?? { x0: m.x, x1: m.x };
    const labelY = markerTop + row * ROW_HEIGHT + ROW_HEIGHT / 2;
    return {
      number: m.change.number,
      x: m.x,
      y0: labelY + 6,
      y1: laneList.length > 0 ? lanesBottom : plotY1,
      label: m.text,
      labelX: span.x0,
      labelY,
    };
  });

  // ---- band and boundary lines ----
  const bandX0 = series.band === null || series.band.from === null ? plotX0 : round(clampX(xOf(series.band.from)));
  const bandRects: ChartModel["bands"] = [];
  for (const [severity, list] of [
    ["warn", bandsResult.warn],
    ["fail", bandsResult.fail],
  ] as const) {
    for (const i of list) {
      bandRects.push({
        severity,
        x0: bandX0,
        x1: plotX1,
        y0: round(clampY(yOf(i.hi))),
        y1: round(clampY(yOf(i.lo))),
      });
    }
  }
  const lines = bandsResult.lines.map((l) => ({
    x0: bandX0,
    x1: plotX1,
    y: round(yOf(l.value)),
    severity: l.severity,
    text: l.text,
  }));

  // ---- right labels, stacked so none overlaps another ----
  // An off-range label sits at its end of the column, on the side it names,
  // and the latest value's label keeps a wider gap from every other (B7).
  const top = plotY0 - 4;
  const bottom = plotY1 + 4;
  const wanted: Wanted[] = rightTexts.map((t) => {
    if (t.kind === "boundary") return { id: t.id, y: lines[Number(t.id.slice(5))]?.y ?? plotY0 };
    if (t.kind === "latest") return { id: t.id, y: yOf(newestValue?.value ?? axis.lo) };
    const above = offRange[Number(t.id.slice(4))]?.side === "above";
    return { id: t.id, y: above ? top : bottom, rank: above ? -1 : 1 };
  });
  const gap = (a: Wanted, b: Wanted): number => (a.id === "latest" || b.id === "latest" ? LATEST_GAP : LINE_HEIGHT);
  const placed = stackLabels(wanted, gap, top, bottom);
  const rightLabels: RightLabel[] = rightTexts.map((t) => ({ ...t, y: round(placed.get(t.id) ?? plotY0) }));

  // ---- marks and line ----
  const laneY = (lane: Lane): number => lanesTop + laneList.indexOf(lane) * LANE_HEIGHT + LANE_HEIGHT / 2;
  const marks: Mark[] = [];
  for (const p of series.points) {
    if (p.kind === "off-axis") continue;
    marks.push({
      key: `${String(p.index)}`,
      x: round(xOf(p.t)),
      y: round(p.kind === "value" ? yOf(p.value ?? 0) : laneY(p.lane ?? "no-value")),
      outcome: p.outcome,
      lane: p.lane,
      point: p,
    });
  }
  const paths = series.segments
    .filter((s) => s.length > 1)
    .map((s) => s.map((p, i) => `${i === 0 ? "M" : "L"}${String(round(xOf(p.t)))} ${String(round(yOf(p.value ?? 0)))}`).join(" "));

  // ---- x axis ----
  const xAxisY = laneList.length > 0 ? lanesBottom + 4 : plotY1;
  const ticks = times.length > 0 ? timeTicks(tMin, tMax) : { step: 0, values: [] };
  const oneDay = times.length === 0 || sameLocalDay(tMin, tMax);
  const xTicks = ticks.values.map((t) => ({ x: round(xOf(t)), label: timeTick(t, ticks.step, oneDay) }));
  const zone = zoneName(tMax);
  const timeNote = times.length === 0 ? "" : oneDay ? `${calendarDay(tMax)} · times in ${zone}` : `Times in ${zone}`;

  // ---- hover/focus columns ----
  const groups = new Map<number, Point[]>();
  for (const p of series.points) {
    const x = round(xOf(p.t));
    groups.set(x, [...(groups.get(x) ?? []), p]);
  }
  const xs = [...groups.keys()].sort((a, b) => a - b);
  // Neighbouring columns meet at the midpoint between their marks, so the
  // pointer always reads the nearest result. Marks 24+ units apart get 24+
  // unit columns; denser marks cannot without overlapping, which would show
  // a neighbour's result, so they take their share (the arrow keys and the
  // table reach every result). The end columns reach past the plot's edge
  // when that is what it takes to be 24 units wide.
  const columns: Column[] = xs.map((x, i) => {
    const prev = xs[i - 1];
    const next = xs[i + 1];
    const x0 = prev === undefined ? Math.min(plotX0, x - MIN_COLUMN / 2) : (prev + x) / 2;
    const x1 = next === undefined ? Math.max(plotX1, x + MIN_COLUMN / 2) : (x + next) / 2;
    return { key: String(x), x, x0: round(x0), x1: round(x1), points: groups.get(x) ?? [] };
  });

  return {
    width: WIDTH,
    height: xAxisY + (times.length > 0 ? 40 : 12),
    plot: { x0: plotX0, x1: plotX1, y0: plotY0, y1: plotY1 },
    series,
    axis,
    yTicks: axis.values.map((v, i) => ({ value: v, y: round(yOf(v)), label: yTickLabels[i] ?? "" })),
    xTicks,
    xAxisY,
    timeNote,
    bands: bandRects,
    lines,
    rightLabels,
    rightX: plotX1 + 8,
    lanes: laneList.map((lane) => ({ lane, label: LANE_LABEL[lane], y: laneY(lane) })),
    marks,
    paths,
    markers,
    streak: streakModel,
    columns,
  };
}

export interface TooltipBox {
  x: number;
  y: number;
  width: number;
  height: number;
  lines: { strong: boolean; text: string; y: number }[];
}

/** At most this many tooltip lines; the table holds everything. */
export const TOOLTIP_MAX_LINES = 12;

/**
 * Where the tooltip for a column sits: beside the crosshair, on the side
 * with room, positioned by an SVG transform (no inline style, decision 14).
 */
export function tooltipBox(model: ChartModel, column: Column): TooltipBox {
  const all = tooltipLines(column.points);
  const lines = all.length > TOOLTIP_MAX_LINES ? [...all.slice(0, TOOLTIP_MAX_LINES - 1), { strong: false, text: "More in the table below" }] : all;
  const width = Math.min(model.width - 8, Math.max(...lines.map((l) => textWidth(l.text, l.strong ? CHAR_WIDTH + 0.5 : CHAR_WIDTH))) + 16);
  const height = lines.length * LINE_HEIGHT + 12;
  const gap = 10;
  let x = column.x + gap;
  if (x + width > model.width - 4) x = column.x - gap - width;
  x = Math.max(4, x);
  const y = Math.max(4, Math.min(model.plot.y0, model.height - height - 4));
  return {
    x: round(x),
    y: round(y),
    width: round(width),
    height,
    lines: lines.map((l, i) => ({ ...l, y: 6 + (i + 1) * LINE_HEIGHT - 3 })),
  };
}
