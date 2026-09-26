/** The pure modules: ages (O4), selections (O8), and status order (O1). */
import { describe, expect, it } from "vitest";
import { describeSelection } from "../lib/selection";
import { countStatuses, sortProblemsFirst, STATUS_ORDER } from "../lib/status";
import { absolute, ago } from "../lib/time";
import { beforeF } from "./fixtures/states";

const T = "2026-09-26T06:56:12.000000+00:00";
const at = (offset: string): number => Date.parse("2026-09-26T06:56:12Z") + parseOffset(offset);
function parseOffset(s: string): number {
  const units: Record<string, number> = { s: 1000, m: 60_000, h: 3_600_000, d: 86_400_000 };
  return s.split(" ").reduce((sum, part) => {
    const unit = units[part.slice(-1)];
    if (unit === undefined) throw new Error(part);
    return sum + Number(part.slice(0, -1)) * unit;
  }, 0);
}

describe("ages are elapsed time, rounded down", () => {
  it.each([
    ["0s", "just now"],
    ["59s", "just now"],
    ["1m", "1 minute ago"],
    ["1m 5s", "1 minute ago"],
    ["59m 59s", "59 minutes ago"],
    ["1h 5s", "1 hour ago"],
    ["2h 59m 59s", "2 hours ago"],
    ["3h 5s", "3 hours ago"],
    ["23h 59m 59s", "23 hours ago"],
    ["1d 5s", "1 day ago"],
    ["1d 23h 59m", "1 day ago"],
    ["2d 5s", "2 days ago"],
    ["7d 3h 5s", "7 days ago"],
    ["400d", "400 days ago"],
  ])("%s later reads '%s'", (offset, expected) => {
    expect(ago(T, at(offset))).toBe(expected);
  });

  it("reads a time in the future as 'just now'", () => {
    expect(ago(T, at("0s") - 3_600_000)).toBe("just now");
  });

  it("does not depend on the zone or DST: 48 hours across a DST change is 2 days", () => {
    // Europe's autumn change is 2026-10-25; ages use epoch milliseconds only.
    const before = "2026-10-24T12:00:00.000000+00:00";
    expect(ago(before, Date.parse("2026-10-26T12:00:05Z"))).toBe("2 days ago");
    expect(ago(before, Date.parse("2026-10-26T11:59:55Z"))).toBe("1 day ago");
  });

  it("says so when a timestamp cannot be read", () => {
    expect(ago("not a time", Date.now())).toBe("at an unknown time");
  });
});

describe("absolute times", () => {
  it("are in the viewer's zone, with the zone stated", () => {
    const shown = absolute(T);
    expect(shown).toContain("14:56:12");
    expect(shown).toMatch(/GMT\+8|SGT|\+08:00/);
    expect(shown).toContain("2026");
  });
});

describe("selections", () => {
  it.each([
    [{}, "all checks"],
    [{ paths: ["checks/sales"] }, "paths: checks/sales"],
    [{ tags: ["pii"], paths: ["checks/sales"] }, "paths: checks/sales; tags: pii"],
    [{ check_ids: ["a", "b"], excludes: ["checks/x"] }, "excludes: checks/x; check ids: a, b"],
    [{ owners: ["sam@example.com"], datasources: ["lake"] }, "datasources: lake; owners: sam@example.com"],
    [{ paths: [] }, "paths: (none)"],
  ])("%j reads '%s'", (selection, expected) => {
    expect(describeSelection(selection)).toBe(expected);
  });
});

describe("status order", () => {
  it("is fail, error, warn, no result, skipped, pass", () => {
    expect(STATUS_ORDER).toEqual(["fail", "error", "warn", "none", "skipped", "pass"]);
  });

  it("sorts stably and does not change the input", () => {
    const input = beforeF.checks.items;
    const before = input.map((c) => c.id);
    const sorted = sortProblemsFirst(input);
    expect(input.map((c) => c.id)).toEqual(before);
    expect(sorted).toHaveLength(input.length);
  });

  it("counts add up to the checks", () => {
    const counts = countStatuses(beforeF.checks.items);
    expect(counts).toEqual({ fail: 4, error: 5, warn: 2, none: 0, skipped: 0, pass: 7, total: 18 });
  });
});
