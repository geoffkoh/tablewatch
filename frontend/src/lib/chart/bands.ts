/**
 * The threshold bands (spec 004 D6): one pure function of (rule, y-domain).
 *
 * A condition's *satisfied* set is a union of intervals on the real line. An
 * `expect` fails outside its set; a `warn` or `fail` trigger fires inside
 * its set. Each set is cut to the domain, and every piece with height is a
 * shaded region. A set that is a single value (`expect != v`, `fail when =
 * v`) has no height: only its line is drawn, in its colour. A set that is
 * everything but one value (`expect = v`) is shaded on both sides of the line,
 * because on this chart white means passing.
 *
 * Warn regions exclude the shaded fail regions, since the engine checks
 * `fail` first; the fail colour is drawn over the warn colour anyway.
 */
import type { Condition, Rule } from "../../api/types";
import { boundaryValues, ruleParts } from "../rule";

export interface Interval {
  lo: number;
  hi: number;
  loClosed: boolean;
  hiClosed: boolean;
}

export type Severity = "warn" | "fail";

export interface BoundaryLine {
  value: number;
  severity: Severity;
  /** The condition's `text`, from the API. */
  text: string;
}

export interface Bands {
  fail: Interval[];
  warn: Interval[];
  /** Lines inside the domain, in ascending value. */
  lines: BoundaryLine[];
}

type IntervalSet = Interval[];

const ALL: Interval = { lo: -Infinity, hi: Infinity, loClosed: false, hiClosed: false };

function interval(lo: number, hi: number, loClosed: boolean, hiClosed: boolean): Interval {
  return { lo, hi, loClosed, hiClosed };
}

/** Where a condition holds. */
export function satisfied(condition: Condition): IntervalSet {
  if (condition.kind === "between") {
    const inside = interval(condition.low, condition.high, true, true);
    return condition.negated ? complement([inside]) : [inside];
  }
  const v = condition.value;
  switch (condition.op) {
    case "<":
      return [interval(-Infinity, v, false, false)];
    case "<=":
      return [interval(-Infinity, v, false, true)];
    case ">":
      return [interval(v, Infinity, false, false)];
    case ">=":
      return [interval(v, Infinity, true, false)];
    case "=":
      return [interval(v, v, true, true)];
    case "!=":
      return [interval(-Infinity, v, false, false), interval(v, Infinity, false, false)];
  }
}

function isEmpty(i: Interval): boolean {
  return i.lo > i.hi || (i.lo === i.hi && !(i.loClosed && i.hiClosed));
}

/** The complement of a disjoint set. */
export function complement(set: IntervalSet): IntervalSet {
  if (set.length === 0) return [ALL];
  const out: Interval[] = [];
  let from = -Infinity;
  let fromClosed = false;
  for (const i of [...set].sort((a, b) => a.lo - b.lo)) {
    if (i.lo !== -Infinity) {
      const gap = interval(from, i.lo, fromClosed, !i.loClosed);
      if (!isEmpty(gap)) out.push(gap);
    }
    from = i.hi;
    fromClosed = !i.hiClosed;
  }
  if (from !== Infinity) out.push(interval(from, Infinity, fromClosed, false));
  return out;
}

function intersectOne(a: Interval, b: Interval): Interval {
  const lo = Math.max(a.lo, b.lo);
  const hi = Math.min(a.hi, b.hi);
  const loClosed = a.lo === b.lo ? a.loClosed && b.loClosed : a.lo > b.lo ? a.loClosed : b.loClosed;
  const hiClosed = a.hi === b.hi ? a.hiClosed && b.hiClosed : a.hi < b.hi ? a.hiClosed : b.hiClosed;
  return interval(lo, hi, loClosed, hiClosed);
}

export function intersect(a: IntervalSet, b: IntervalSet): IntervalSet {
  const out: Interval[] = [];
  for (const x of a) for (const y of b) {
    const i = intersectOne(x, y);
    if (!isEmpty(i)) out.push(i);
  }
  return out.sort((p, q) => p.lo - q.lo);
}

/** Pieces with height: what gets shaded. */
function withHeight(set: IntervalSet): IntervalSet {
  return set.filter((i) => i.hi > i.lo);
}

/** The regions and lines for a rule over a y-domain [lo, hi]. */
export function bands(rule: Rule, domain: readonly [number, number]): Bands {
  const within: IntervalSet = [interval(domain[0], domain[1], true, true)];
  let failing: IntervalSet = [];
  let warning: IntervalSet = [];
  const lines: BoundaryLine[] = [];
  for (const part of ruleParts(rule)) {
    const holds = satisfied(part.condition);
    const region = part.role === "expect" ? complement(holds) : holds;
    const shaded = withHeight(intersect(region, within));
    if (part.role === "warn") warning = [...warning, ...shaded];
    else failing = [...failing, ...shaded];
    const severity: Severity = part.role === "warn" ? "warn" : "fail";
    for (const value of boundaryValues(part.condition)) {
      if (value >= domain[0] && value <= domain[1]) lines.push({ value, severity, text: part.condition.text });
    }
  }
  const warnOnly = failing.length === 0 ? warning : withHeight(intersect(warning, complement(failing)));
  return {
    fail: failing.sort((a, b) => a.lo - b.lo),
    warn: warnOnly.sort((a, b) => a.lo - b.lo),
    lines: lines.sort((a, b) => a.value - b.value),
  };
}

/** "[5, 25]", "[0, 10)", "(500, 600]": for tests and debugging. */
export function intervalText(i: Interval): string {
  return `${i.loClosed ? "[" : "("}${String(i.lo)}, ${String(i.hi)}${i.hiClosed ? "]" : ")"}`;
}
