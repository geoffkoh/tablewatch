/**
 * Round tick values for the y-axis (by unit) and the x-axis (time, in the
 * viewer's zone). Pure, apart from the platform's time zone for x ticks.
 */
import type { Unit } from "../../api/types";

/** At most this many intervals between ticks. */
export const MAX_INTERVALS = 6;

export interface Ticks {
  lo: number;
  hi: number;
  step: number;
  values: number[];
}

// Seconds, minutes, hours and days, then whole multiples of 30 days.
const DURATION_STEPS: readonly number[] = [
  1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10_800, 21_600, 43_200, 86_400, 172_800, 604_800,
  1_209_600, 2_592_000,
];

function oneTwoFive(minimum: number): number[] {
  const steps: number[] = [];
  const start = Math.floor(Math.log10(minimum)) - 1;
  for (let e = start; e <= start + 3; e += 1) {
    for (const m of [1, 2, 5]) steps.push(clean(m * 10 ** e));
  }
  return steps;
}

/** Remove floating-point dust: 0.30000000000000004 → 0.3. */
export function clean(x: number): number {
  return Number.parseFloat(x.toPrecision(12));
}

function candidateSteps(span: number, unit: Unit | null): number[] {
  const rough = span / MAX_INTERVALS;
  if (unit === "duration" && rough >= 1) {
    const top = DURATION_STEPS[DURATION_STEPS.length - 1] ?? 2_592_000;
    if (rough <= top) return [...DURATION_STEPS];
    return oneTwoFive(rough / top).map((m) => m * top);
  }
  const steps = oneTwoFive(rough);
  // Counts are whole numbers: never a tick at 0.5 rows.
  return unit === "count" ? steps.filter((s) => s >= 1) : steps;
}

/**
 * Extend [lo, hi] outwards to round ticks, with the smallest round step that
 * gives at most MAX_INTERVALS intervals.
 */
export function niceTicks(lo: number, hi: number, unit: Unit | null): Ticks {
  let a = lo;
  let b = hi;
  if (!(b > a)) {
    a = lo - 1;
    b = lo + 1;
  }
  const steps = candidateSteps(b - a, unit);
  let chosen = steps[steps.length - 1] ?? 1;
  for (const step of steps) {
    const intervals = Math.ceil(clean(b / step)) - Math.floor(clean(a / step));
    if (intervals <= MAX_INTERVALS) {
      chosen = step;
      break;
    }
  }
  const first = Math.floor(clean(a / chosen));
  const last = Math.ceil(clean(b / chosen));
  const values: number[] = [];
  for (let i = first; i <= last; i += 1) values.push(clean(i * chosen));
  return { lo: clean(first * chosen), hi: clean(last * chosen), step: chosen, values };
}

// ---- time ------------------------------------------------------------------

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Time steps in ms; days and longer are counted in local calendar days. */
const TIME_STEPS: readonly number[] = [
  SECOND,
  5 * SECOND,
  15 * SECOND,
  30 * SECOND,
  MINUTE,
  5 * MINUTE,
  15 * MINUTE,
  30 * MINUTE,
  HOUR,
  3 * HOUR,
  6 * HOUR,
  12 * HOUR,
  DAY,
  2 * DAY,
  7 * DAY,
  14 * DAY,
  30 * DAY,
  90 * DAY,
  365 * DAY,
];

export interface TimeTicks {
  step: number;
  values: number[];
}

/** The zone's offset from UTC at `t`, in ms (east positive). */
function offsetAt(t: number): number {
  return -new Date(t).getTimezoneOffset() * MINUTE;
}

/** The first tick at or after `t` for a step, aligned on the local clock. */
function firstTick(t: number, step: number): number {
  if (step < DAY) {
    const offset = offsetAt(t);
    return Math.ceil((t + offset) / step) * step - offset;
  }
  const d = new Date(t);
  const partial = d.getHours() > 0 || d.getMinutes() > 0 || d.getSeconds() > 0 || d.getMilliseconds() > 0;
  d.setHours(0, 0, 0, 0);
  if (step >= 365 * DAY) {
    if (partial || d.getDate() !== 1 || d.getMonth() !== 0) d.setFullYear(d.getFullYear() + 1, 0, 1);
  } else if (step >= 30 * DAY) {
    if (partial || d.getDate() !== 1) d.setMonth(d.getMonth() + 1, 1);
  } else if (partial) {
    d.setDate(d.getDate() + 1);
  }
  return d.getTime();
}

function advance(t: number, step: number): number {
  if (step < DAY) return t + step;
  const d = new Date(t);
  if (step >= 365 * DAY) d.setFullYear(d.getFullYear() + Math.round(step / (365 * DAY)));
  else if (step >= 30 * DAY) d.setMonth(d.getMonth() + Math.round(step / (30 * DAY)));
  else d.setDate(d.getDate() + Math.round(step / DAY));
  return d.getTime();
}

/** Round times inside [t0, t1], at most MAX_INTERVALS + 1 of them. */
export function timeTicks(t0: number, t1: number): TimeTicks {
  const span = Math.max(t1 - t0, SECOND);
  let chosen = TIME_STEPS[TIME_STEPS.length - 1] ?? DAY;
  for (const step of TIME_STEPS) {
    if (span / step <= MAX_INTERVALS) {
      chosen = step;
      break;
    }
  }
  const values: number[] = [];
  for (let t = firstTick(t0, chosen); t <= t1 && values.length < 50; t = advance(t, chosen)) values.push(t);
  return { step: chosen, values };
}

export const TIME = { SECOND, MINUTE, HOUR, DAY } as const;
