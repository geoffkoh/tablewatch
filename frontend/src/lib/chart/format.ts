/**
 * Axis labels, by unit (spec 004 D10). This is the only place the browser
 * formats a number, and it formats only axis ticks and off-range edge labels
 * (decision 12). A result's value is always `display_value` from Python, and
 * a rule's condition is always `rule.*.text`.
 */
import type { Unit } from "../../api/types";

const MAX_DECIMALS = 6;

function numberFormat(decimals: number): Intl.NumberFormat {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: Math.min(MAX_DECIMALS, Math.max(0, decimals)) });
}

/** How many decimals a tick step needs: 0.25 needs 2, 5 needs 0. */
export function decimalsFor(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 2;
  for (let d = 0; d <= MAX_DECIMALS; d += 1) {
    const scaled = step * 10 ** d;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9 * Math.max(1, scaled)) return d;
  }
  return MAX_DECIMALS;
}

function plain(value: number, decimals: number): string {
  // -0 would print as "-0".
  const v = Object.is(value, -0) ? 0 : value;
  return numberFormat(decimals).format(v);
}

const DURATION_UNITS: readonly (readonly [string, number])[] = [
  ["d", 86_400],
  ["h", 3_600],
  ["m", 60],
  ["s", 1],
];

/** 21600 → "6h", 90 → "1m 30s", 93600 → "1d 2h", -25200 → "-7h", 0.5 → "0.5s". */
export function formatDuration(seconds: number, decimals = 2): string {
  const sign = seconds < 0 ? "-" : "";
  const abs = Math.abs(seconds);
  if (abs < 60) return `${sign}${plain(abs, decimals)}s`;
  const total = Math.round(abs);
  for (let i = 0; i < DURATION_UNITS.length; i += 1) {
    const [name, size] = DURATION_UNITS[i] ?? ["s", 1];
    if (total < size) continue;
    const whole = Math.floor(total / size);
    let text = `${String(whole)}${name}`;
    const next = DURATION_UNITS[i + 1];
    if (next !== undefined) {
      const rest = Math.floor((total - whole * size) / next[1]);
      if (rest > 0) text += ` ${String(rest)}${next[0]}`;
    }
    return sign + text;
  }
  return `${sign}0s`;
}

/**
 * A tick label. `step` is the distance between ticks, when known: it sets
 * how many decimals a count, number or percent shows. A null unit (a metric
 * this version does not know) formats as a plain number.
 */
export function formatTick(value: number, unit: Unit | null, step?: number): string {
  const decimals = step === undefined ? 2 : decimalsFor(step);
  switch (unit) {
    case "percent":
      return `${plain(value, decimals)}%`;
    case "duration":
      return formatDuration(value, decimals);
    case "count":
    case "number":
    case null:
      return plain(value, decimals);
  }
}

/** The axis title's unit part: "missing_percent (%)", "freshness (age)". */
export function unitLabel(unit: Unit | null): string {
  switch (unit) {
    case "percent":
      return "%";
    case "duration":
      return "age";
    case "count":
      return "count";
    case "number":
      return "value";
    case null:
      return "unit unknown";
  }
}
