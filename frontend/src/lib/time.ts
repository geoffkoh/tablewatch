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

const ZONE = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" });

/** The viewer's zone at a time, as the platform names it: "GMT+8", "CEST". */
export function zoneName(ms: number): string {
  const part = ZONE.formatToParts(new Date(Number.isNaN(ms) ? 0 : ms)).find((p) => p.type === "timeZoneName");
  return part?.value ?? "local time";
}

const NO_ZONE = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/** The full time in the viewer's zone, without the zone: for a table whose caption names it. */
export function localTime(iso: string): string {
  const ms = parseTimestamp(iso);
  if (Number.isNaN(ms)) return iso;
  return NO_ZONE.format(new Date(ms));
}

const SECONDS = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const MINUTES = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const DAY_MINUTES = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const DAY_ONLY = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const MONTH = new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" });
const FULL_DAY = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });

const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;

/**
 * An x-axis label in the viewer's zone (the axis names the zone). Within one
 * day only the time is shown; the axis states the date once.
 */
export function timeTick(ms: number, step: number, oneDay: boolean): string {
  const d = new Date(ms);
  if (step >= 30 * DAY_MS) return MONTH.format(d);
  if (step >= DAY_MS) return DAY_ONLY.format(d);
  if (!oneDay) return DAY_MINUTES.format(d);
  return step < MINUTE_MS ? SECONDS.format(d) : MINUTES.format(d);
}

/** "Sep 26, 2026". */
export function calendarDay(ms: number): string {
  return FULL_DAY.format(new Date(ms));
}

/** True when two times fall on the same local calendar day. */
export function sameLocalDay(a: number, b: number): boolean {
  return calendarDay(a) === calendarDay(b);
}

const YEAR = new Intl.DateTimeFormat(undefined, { year: "numeric" });

/**
 * A streak's start as a point in time, in the viewer's zone (spec 017 P2):
 * "10:05 today" on the same local day as now, "Sep 19" in the same local
 * year, otherwise "Dec 31, 2025". A point, not a duration: it stays true when
 * the latest result is old. Uses the same `Intl` zone as `absolute`.
 */
export function sincePoint(iso: string, nowMs: number): string {
  const ms = parseTimestamp(iso);
  if (Number.isNaN(ms)) return "an unknown time";
  const d = new Date(ms);
  if (sameLocalDay(ms, nowMs)) return `${MINUTES.format(d)} today`;
  if (YEAR.format(d) === YEAR.format(new Date(nowMs))) return DAY_ONLY.format(d);
  return FULL_DAY.format(d);
}
