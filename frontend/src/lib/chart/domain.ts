/**
 * The y-domain (spec 004 D10): one pure function of the plotted values and
 * the rule's boundaries.
 *
 * 1. The values' extent is the base. A single value (or all equal) extends
 *    to 0, so it is drawn against a baseline rather than alone in space.
 * 2. Zero joins an all-positive extent when that at most doubles its height,
 *    and always joins when any value is negative: a negative freshness (a
 *    timestamp in the future) must be seen below 0, never clamped to it.
 * 3. A boundary joins when the domain with it is at most twice the base's
 *    height, so the values keep at least half the plot. A boundary left out
 *    is drawn as an edge label ("10,000 above"), never squashing the values.
 * 4. With no values (every result an error), the domain is the boundaries
 *    and 0.
 * 5. The result is extended outwards to round ticks for the unit.
 */
import type { Unit } from "../../api/types";
import { niceTicks, type Ticks } from "./ticks";

export interface OffRange {
  value: number;
  side: "above" | "below";
}

export interface YAxis extends Ticks {
  offRange: OffRange[];
}

type Range = readonly [number, number];

function hull(range: Range, v: number): Range {
  return [Math.min(range[0], v), Math.max(range[1], v)];
}

const height = (r: Range): number => r[1] - r[0];

/** The domain before rounding to ticks. */
export function rawDomain(values: readonly number[], boundaries: readonly number[]): Range {
  const finite = values.filter(Number.isFinite);
  const bounds = boundaries.filter(Number.isFinite);
  if (finite.length === 0) {
    const range = bounds.reduce<Range>((r, b) => hull(r, b), [0, 0]);
    return height(range) > 0 ? range : [0, 1];
  }
  const lo = Math.min(...finite);
  const hi = Math.max(...finite);
  let base: Range;
  if (lo === hi) base = lo === 0 ? [0, 1] : hull([lo, lo], 0);
  else if (lo < 0) base = hull([lo, hi], 0);
  else base = hi - 0 <= 2 * (hi - lo) ? [0, hi] : [lo, hi];
  const limit = 2 * height(base);
  let range = base;
  const byDistance = [...bounds].sort(
    (a, b) => distance(base, a) - distance(base, b) || a - b,
  );
  for (const b of byDistance) {
    const next = hull(range, b);
    if (height(next) <= limit) range = next;
  }
  return range;
}

function distance(range: Range, v: number): number {
  if (v < range[0]) return range[0] - v;
  if (v > range[1]) return v - range[1];
  return 0;
}

/** The y-axis: a round domain, its ticks, and the boundaries left off it. */
export function yAxis(values: readonly number[], boundaries: readonly number[], unit: Unit | null): YAxis {
  const [lo, hi] = rawDomain(values, boundaries);
  const ticks = niceTicks(lo, hi, unit);
  const offRange: OffRange[] = [];
  for (const b of [...new Set(boundaries)].sort((x, y) => x - y)) {
    if (b > ticks.hi) offRange.push({ value: b, side: "above" });
    else if (b < ticks.lo) offRange.push({ value: b, side: "below" });
  }
  return { ...ticks, offRange };
}
