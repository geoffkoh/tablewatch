/**
 * The Alerts page's pure parts (spec 041 P5): the event filter kept in the
 * URL (`?event=`, the same `location.search` pattern as the explorer's
 * `lib/explorer.ts`), and every wording — event, "was &lt;previous&gt;" and
 * deliveries (D5) — so each reads the same whether it is tested here or on
 * the page.
 */
import type { AlertDelivery, AlertEvent, Outcome } from "../api/types";
import type { Status } from "./status";

/** One page of alerts: the server's default (`routes.py`'s `limit=50`). */
export const ALERTS_LIMIT = 50;

/** The event filter's values, "all" first (P5). */
export type AlertFilter = "all" | AlertEvent;
export const ALERT_FILTERS: readonly AlertFilter[] = ["all", "failing", "erroring", "recovered"];

/** The filter's label, as a radio button reads it. */
export const ALERT_FILTER_LABELS: Readonly<Record<AlertFilter, string>> = {
  all: "All",
  failing: "Failing",
  erroring: "Erroring",
  recovered: "Recovered",
};

function isAlertFilter(value: string): value is AlertFilter {
  return (ALERT_FILTERS as readonly string[]).includes(value);
}

/** The filter from `?event=`; an unknown or missing value reads "all" (every event shown). */
export function parseAlertsFilter(search: string): AlertFilter {
  const value = new URLSearchParams(search).get("event");
  return value !== null && isAlertFilter(value) && value !== "all" ? value : "all";
}

/** The filter as a `location.search` string: "" for "all", `?event=<value>` otherwise. */
export function alertsSearch(filter: AlertFilter): string {
  if (filter === "all") return "";
  const params = new URLSearchParams();
  params.set("event", filter);
  return `?${params.toString()}`;
}

/** The `event` the API call narrows to; `undefined` (no parameter) for "all". */
export function alertsEventParam(filter: AlertFilter): AlertEvent | undefined {
  return filter === "all" ? undefined : filter;
}

/** "Started failing", "Started erroring", "Recovered" (P5). */
export function alertEventText(event: AlertEvent): string {
  switch (event) {
    case "failing":
      return "Started failing";
    case "erroring":
      return "Started erroring";
    case "recovered":
      return "Recovered";
  }
}

/** The status icon beside an event: what it means in the app's existing vocabulary (O1). */
export function alertEventStatus(event: AlertEvent): Status {
  switch (event) {
    case "failing":
      return "fail";
    case "erroring":
      return "error";
    case "recovered":
      return "pass";
  }
}

/**
 * The continuous-verb words the app already uses for a streak or a count
 * (`SINCE_PREFIX`, `datasets.ts`'s `SUMMARY_WORDS`), plus `erroring` — this
 * page's own word for `error`, coined alongside "Started erroring" so the
 * two never disagree.
 */
const PREVIOUS_WORDS: Readonly<Record<Outcome, string>> = {
  pass: "passing",
  warn: "warning",
  fail: "failing",
  error: "erroring",
  skipped: "skipped",
};

/** "was &lt;previous&gt;"; null when there is no previous outcome to report (D4). */
export function previousText(previous: Outcome | null): string | null {
  return previous === null ? null : `was ${PREVIOUS_WORDS[previous]}`;
}

function plural(n: number, word: string): string {
  return `${String(n)} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * One delivery's line (D5, A8, A8a): "Sent to ops", "Pending for hook (2
 * attempts)" (1 attempt singular), "Gave up on hook after 5 attempts", or
 * "Gave up on hook (no attempts sent)" when nothing was ever sent.
 */
export function deliveryText(delivery: AlertDelivery): string {
  switch (delivery.status) {
    case "sent":
      return `Sent to ${delivery.notifier}`;
    case "pending":
      return `Pending for ${delivery.notifier} (${plural(delivery.attempts, "attempt")})`;
    case "abandoned":
      return delivery.attempts > 0
        ? `Gave up on ${delivery.notifier} after ${String(delivery.attempts)} attempts`
        : `Gave up on ${delivery.notifier} (no attempts sent)`;
  }
}

/**
 * Every delivery line for an alert (D5, P4): `null` (the run was not keyed,
 * nothing recorded at all) reads "Not recorded (run had no --run-key)"; `[]`
 * (keyed, nothing recorded for this check) reads "No notification recorded";
 * otherwise one line per notifier, in the order the API sent them.
 */
export function deliveriesText(deliveries: readonly AlertDelivery[] | null): string[] {
  if (deliveries === null) return ["Not recorded (run had no --run-key)"];
  if (deliveries.length === 0) return ["No notification recorded"];
  return deliveries.map(deliveryText);
}
