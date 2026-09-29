/**
 * Axis labels and threshold labels, by unit (spec 004 D10). This is the only
 * place the browser formats a number, and it formats only axis ticks, off-range
 * edge labels, and the value on each of a `between`'s two boundary lines
 * (decision 12, extended by spec 012). A result's value is always
 * `display_value` from Python, and a condition shown whole is always
 * `rule.*.text`.
 */
import type { Unit } from "../../api/types";

/**
 * Enough for a step as fine as 1e-20: ticks over values that differ only in
 * their last digits (float sums that wobble run to run) must not all print
 * the same label.
 */
const MAX_DECIMALS = 20;
/** At and above this magnitude a tick is written 1.5E21, not 22 digits and commas. */
const SCIENTIFIC_FROM = 1e21;

function numberFormat(decimals: number): Intl.NumberFormat {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: Math.min(MAX_DECIMALS, Math.max(0, decimals)) });
}

const SCIENTIFIC = new Intl.NumberFormat("en-US", { notation: "scientific", maximumFractionDigits: 3 });

/** How many decimals a tick step needs: 0.25 needs 2, 5 needs 0. */
export function decimalsFor(step: number): number {
  if (!Number.isFinite(step) || step <= 0) return 2;
  for (let d = 0; d <= MAX_DECIMALS; d += 1) {
    const scaled = step * 10 ** d;
    // A step that rounds to 0 is not whole yet: 5e-10 needs 10 decimals, not 0.
    if (Math.round(scaled) !== 0 && Math.abs(scaled - Math.round(scaled)) < 1e-9 * Math.max(1, scaled)) return d;
  }
  return MAX_DECIMALS;
}

function plain(value: number, decimals: number): string {
  // -0 would print as "-0".
  const v = Object.is(value, -0) ? 0 : value;
  if (Math.abs(v) >= SCIENTIFIC_FROM) return SCIENTIFIC.format(v);
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

/**
 * A threshold's value, never rounded (spec 012 B6): the shortest decimal that
 * reads back as the same number, so 0.125 stays "0.125" where a tick would
 * show "0.13". Used for off-range edge labels and `between` boundary lines.
 * A duration still shows its largest two units (the axis's formatter).
 */
export function formatThreshold(value: number, unit: Unit | null): string {
  switch (unit) {
    case "percent":
      return `${plain(value, MAX_DECIMALS)}%`;
    case "duration":
      return formatDuration(value, MAX_DECIMALS);
    case "count":
    case "number":
    case null:
      return plain(value, MAX_DECIMALS);
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
