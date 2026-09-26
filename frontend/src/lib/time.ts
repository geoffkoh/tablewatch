/**
 * Ages and absolute times. No date library: ages are elapsed time, and
 * absolute times use the platform's `Intl`.
 *
 * Ages are the difference in epoch milliseconds, rounded **down** (O4): "2
 * days" means at least 48 hours, and neither DST nor the viewer's time zone
 * ever changes an age. Under one minute, and for a time in the future (clock
 * skew), the age is "just now".
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function plural(n: number, unit: string): string {
  return `${String(n)} ${unit}${n === 1 ? "" : "s"}`;
}

/** Parse an API timestamp; NaN when it is not one. */
export function parseTimestamp(iso: string): number {
  return Date.parse(iso);
}

/** Elapsed time, rounded down: "just now", "5 minutes", "3 hours", "7 days". */
export function elapsed(fromMs: number, nowMs: number): string | null {
  const diff = nowMs - fromMs;
  if (Number.isNaN(diff)) return null;
  if (diff < MINUTE) return null;
  if (diff < HOUR) return plural(Math.floor(diff / MINUTE), "minute");
  if (diff < DAY) return plural(Math.floor(diff / HOUR), "hour");
  return plural(Math.floor(diff / DAY), "day");
}

/** "3 hours ago", or "just now". */
export function ago(iso: string, nowMs: number): string {
  const ms = parseTimestamp(iso);
  if (Number.isNaN(ms)) return "at an unknown time";
  const span = elapsed(ms, nowMs);
  return span === null ? "just now" : `${span} ago`;
}

const ABSOLUTE = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
});

/** The full time in the viewer's time zone, with the zone stated. */
export function absolute(iso: string): string {
  const ms = parseTimestamp(iso);
  if (Number.isNaN(ms)) return iso;
  return ABSOLUTE.format(new Date(ms));
}
