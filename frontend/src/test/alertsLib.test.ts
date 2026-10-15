/**
 * The Alerts page's pure parts (spec 041 P5, D5): the `?event=` query, and
 * every wording — event, "was &lt;previous&gt;" and deliveries.
 */
import { describe, expect, it } from "vitest";
import type { AlertDelivery, Outcome } from "../api/types";
import {
  ALERT_FILTERS,
  alertEventStatus,
  alertEventText,
  alertsEventParam,
  alertsSearch,
  deliveriesText,
  deliveryText,
  parseAlertsFilter,
  previousText,
} from "../lib/alerts";

describe("parseAlertsFilter", () => {
  it("reads 'all' when there is no ?event=", () => {
    expect(parseAlertsFilter("")).toBe("all");
  });

  it.each(["failing", "erroring", "recovered"] as const)("reads %s from ?event=%s", (value) => {
    expect(parseAlertsFilter(`?event=${value}`)).toBe(value);
  });

  it("an unknown value, or the literal 'all', reads 'all'", () => {
    expect(parseAlertsFilter("?event=bogus")).toBe("all");
    expect(parseAlertsFilter("?event=all")).toBe("all");
  });
});

describe("alertsSearch", () => {
  it("is '' for 'all'", () => {
    expect(alertsSearch("all")).toBe("");
  });

  it("round-trips every other filter through parseAlertsFilter", () => {
    for (const filter of ALERT_FILTERS) {
      if (filter === "all") continue;
      expect(parseAlertsFilter(alertsSearch(filter))).toBe(filter);
    }
  });
});

describe("alertsEventParam", () => {
  it("is undefined for 'all', and itself otherwise", () => {
    expect(alertsEventParam("all")).toBeUndefined();
    expect(alertsEventParam("failing")).toBe("failing");
  });
});

describe("alertEventText (P5)", () => {
  it.each([
    ["failing", "Started failing"],
    ["erroring", "Started erroring"],
    ["recovered", "Recovered"],
  ] as const)("%s reads '%s'", (event, text) => {
    expect(alertEventText(event)).toBe(text);
  });
});

describe("alertEventStatus", () => {
  it.each([
    ["failing", "fail"],
    ["erroring", "error"],
    ["recovered", "pass"],
  ] as const)("%s is the %s status icon", (event, s) => {
    expect(alertEventStatus(event)).toBe(s);
  });
});

describe("previousText (D4)", () => {
  it("is null, so 'was' is omitted entirely", () => {
    expect(previousText(null)).toBeNull();
  });

  it.each([
    ["pass", "was passing"],
    ["warn", "was warning"],
    ["fail", "was failing"],
    ["error", "was erroring"],
    ["skipped", "was skipped"],
  ] as [Outcome, string][])("%s reads '%s'", (previous, text) => {
    expect(previousText(previous)).toBe(text);
  });
});

function delivery(overrides: Partial<AlertDelivery>): AlertDelivery {
  return { notifier: "ops", status: "sent", attempts: 1, sent_at: null, ...overrides };
}

describe("deliveryText (D5, A8, A8a)", () => {
  it("sent reads 'Sent to <notifier>'", () => {
    expect(deliveryText(delivery({ notifier: "ops", status: "sent" }))).toBe("Sent to ops");
  });

  it("pending reads 'Pending for <notifier> (N attempts)', 1 attempt singular", () => {
    expect(deliveryText(delivery({ notifier: "hook", status: "pending", attempts: 2 }))).toBe(
      "Pending for hook (2 attempts)",
    );
    expect(deliveryText(delivery({ notifier: "hook", status: "pending", attempts: 1 }))).toBe(
      "Pending for hook (1 attempt)",
    );
  });

  it("abandoned with attempts reads 'Gave up on <notifier> after N attempts' (A8)", () => {
    expect(deliveryText(delivery({ notifier: "hook", status: "abandoned", attempts: 5 }))).toBe(
      "Gave up on hook after 5 attempts",
    );
  });

  it("abandoned with no attempts reads 'Gave up on <notifier> (no attempts sent)' (A8a)", () => {
    expect(deliveryText(delivery({ notifier: "hook", status: "abandoned", attempts: 0 }))).toBe(
      "Gave up on hook (no attempts sent)",
    );
  });
});

describe("deliveriesText (P4, A9)", () => {
  it("null reads 'Not recorded (run had no --run-key)' (A9)", () => {
    expect(deliveriesText(null)).toEqual(["Not recorded (run had no --run-key)"]);
  });

  it("[] reads 'No notification recorded'", () => {
    expect(deliveriesText([])).toEqual(["No notification recorded"]);
  });

  it("every delivery gets its own line, in order", () => {
    const lines = deliveriesText([
      delivery({ notifier: "ops", status: "sent" }),
      delivery({ notifier: "hook", status: "abandoned", attempts: 5 }),
    ]);
    expect(lines).toEqual(["Sent to ops", "Gave up on hook after 5 attempts"]);
  });
});
