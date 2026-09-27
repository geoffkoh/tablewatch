/**
 * The check page, scenario by scenario (spec 004, D1–D20). Every API
 * response is a fixture typed against the generated contract.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import packageJsonText from "../../package.json?raw";
import { App } from "../App";
import type { CheckDetail, HistoryEntry } from "../api/types";
import { renamedState } from "./fixtures/derived";
import {
  detailOf,
  edited,
  EDITED_ID,
  editedPending,
  emailHistory,
  emailHistoryBeforeF,
  emailSummary,
  entry,
  IO_ERROR,
  metricChangedBack,
  page,
  recordedHistory,
  rowsHistory,
} from "./fixtures/detail";
import { beforeF, interrupted, recorded, RUN_ID, STARTED } from "./fixtures/states";
import {
  CLOCK,
  checkUrls,
  notFound,
  ok,
  olderUrl,
  renderCheck,
  renderOverview,
  rowFor,
  setClock,
  stubCheckServer,
  text,
  UNAVAILABLE,
} from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

const EMAIL = "b1ceb8262d8b5441";

function historyRows(): HTMLElement[] {
  const table = screen.getByRole("table");
  const [, body] = within(table).getAllByRole("rowgroup");
  if (body === undefined) throw new Error("no table body");
  return within(body).getAllByRole("row");
}

function chart(): SVGSVGElement {
  const svg = document.querySelector<SVGSVGElement>("svg.chart__svg");
  if (svg === null) throw new Error("no chart");
  return svg;
}

function marks(lane?: string): Element[] {
  return Array.from(chart().querySelectorAll(`.chart__marks .mark${lane === undefined ? "" : `[data-lane="${lane}"]`}`));
}

function section(name: string): HTMLElement {
  return screen.getByRole("region", { name });
}

async function renderEmail(state = interrupted, history = emailHistory): Promise<void> {
  await renderCheck(EMAIL, { check: ok(detailOf(state, EMAIL)), history: ok(history) });
}

describe("D1: every check has a link, and the link survives a reload", () => {
  it("links every check name on the overview to /checks/<id>, encoded", async () => {
    const fixture = structuredClone(recorded);
    const first = fixture.checks.items[0];
    if (first === undefined) throw new Error("no checks");
    first.id = "customer-email-completeness";
    const colon = fixture.checks.items[1];
    if (colon === undefined) throw new Error("no checks");
    colon.id = "orders:volume";
    await renderOverview(fixture);
    for (const check of fixture.checks.items) {
      const link = within(rowFor(check.id)).getByRole("link", { name: check.name });
      expect(link.getAttribute("href")).toBe(`/checks/${encodeURIComponent(check.id)}`);
    }
    expect(within(rowFor(EMAIL)).getByRole("link").getAttribute("href")).toBe("/checks/b1ceb8262d8b5441");
    expect(within(rowFor("customer-email-completeness")).getByRole("link").getAttribute("href")).toBe(
      "/checks/customer-email-completeness",
    );
    expect(within(rowFor("orders:volume")).getByRole("link").getAttribute("href")).toBe("/checks/orders%3Avolume");
  });

  it.each([`/checks/${EMAIL}`, `/checks/${EMAIL}/`])("renders the check page for %s", async (path) => {
    await renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(emailHistory) }, path);
    expect(screen.queryByRole("heading", { name: "Page not found" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("missing_percent(email) < 5%");
  });

  it.each(["/checks/", "/checks/a/b", "/checks/..", "/checks/%2e%2e", "/checks/a%2Fb", "/checks/a%3Fb", "/checks/%", `/checks/${"a".repeat(65)}`])(
    "%s is page not found, with no request made",
    (path) => {
      const fetchMock = vi.fn(() => Promise.reject(new Error("no request expected")));
      vi.stubGlobal("fetch", fetchMock);
      render(<App path={path} />);
      expect(screen.getByRole("heading", { name: "Page not found" })).toBeTruthy();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("links back to the overview", async () => {
    await renderEmail();
    expect(screen.getByRole("link", { name: "Back to the overview" }).getAttribute("href")).toBe("/");
  });

  it("requests the five endpoints, with the id encoded", async () => {
    const id = "orders:volume";
    const detail: CheckDetail = { ...detailOf(interrupted, EMAIL), id };
    const fetchMock = stubCheckServer(id, { check: ok(detail), history: ok(emailHistory) });
    render(<App path="/checks/orders%3Avolume" />);
    await screen.findByRole("table");
    const urls = checkUrls(id);
    expect(fetchMock.mock.calls.map((c) => String(c[0])).sort()).toEqual(
      [urls.project, urls.check, urls.history, urls.runs, urls.sql].sort(),
    );
    expect(urls.sql).toBe("/api/v1/checks/orders%3Avolume/sql");
    expect(urls.check).toBe("/api/v1/checks/orders%3Avolume");
    expect(urls.history).toBe("/api/v1/checks/orders%3Avolume/history?limit=200");
  });
});

describe("D2: what the check is", () => {
  it("shows the name, dataset, datasource, owner, tags, source and full id", async () => {
    await renderEmail(recorded, recordedHistory(EMAIL));
    const identity = text(screen.getByRole("heading", { level: 1 }).closest("section") ?? document.body);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("missing_percent(email) < 5%");
    for (const expected of [
      "sales.customers",
      "lake",
      "sales-data@example.com",
      "example",
      "sales",
      "tier-1",
      "checks/sales/customers.yml:6:5",
      EMAIL,
    ]) {
      expect(identity).toContain(expected);
    }
  });

  it("shows a named check's name and, separately, its expression; the title names the check", async () => {
    const id = "32867fbe86f483f3";
    await renderCheck(id, { check: ok(detailOf(recorded, id)), history: ok(recordedHistory(id)) });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Order volume");
    expect(screen.getByText("row_count | warn when < 100 | fail when = 0", { selector: "code" })).toBeTruthy();
    expect(document.title).toBe("Order volume · tablewatch");
  });

  it("keeps the project name in the header without a second h1", async () => {
    await renderEmail();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(text(screen.getByRole("banner"))).toContain("retail-example");
  });
});

describe("D3: the rule in words", () => {
  const rule = (): HTMLElement => section("Rule");

  it.each([
    [EMAIL, [["Expected", "< 5%"]]],
    [
      "41e58afff9c48a46",
      [
        ["Warn when", "> 1d"],
        ["Fail when", "> 7d"],
      ],
    ],
    ["fbc3aa0b93b66eee", [["Expected", "= 0"]]],
  ])("%s reads %j", async (id, parts) => {
    await renderCheck(id, { check: ok(detailOf(recorded, id)), history: ok(recordedHistory(id)) });
    const shown = Array.from(rule().querySelectorAll("dl.rule > div")).map((d) => [
      d.querySelector("dt")?.textContent,
      d.querySelector("dd")?.textContent,
    ]);
    expect(shown).toEqual(parts);
  });

  it("shows the API's text, never a threshold formatted from the numbers", async () => {
    const detail = detailOf(recorded, EMAIL);
    detail.rule = { expect: { kind: "compare", op: "<", value: 0.05, text: "< 5 percent, as written" }, warn: null, fail: null };
    await renderCheck(EMAIL, { check: ok(detail), history: ok(recordedHistory(EMAIL)) });
    expect(text(rule())).toContain("< 5 percent, as written");
    expect(text(rule())).not.toContain("0.05");
    expect(text(document.querySelector(".chart") ?? document.body)).toContain("< 5 percent, as written");
  });

  it("says the rule is the one in the check files as loaded, with its age", async () => {
    await renderEmail();
    expect(text(rule())).toContain("from the check files loaded 3 hours ago");
    expect(rule().querySelector("time")?.getAttribute("datetime")).toBe(interrupted.project.loaded_at);
  });
});

describe("D4: the latest result in the overview's words", () => {
  const latest = (): HTMLElement => section("Latest result");

  it("A, B, E: could not evaluate, the message, last evaluated fail, failing since A", async () => {
    await renderCheck(EMAIL, { check: ok(detailOf(beforeF, EMAIL)), history: ok(emailHistoryBeforeF) });
    const content = text(latest());
    expect(content).toContain("Could not evaluate");
    expect(content).toContain(IO_ERROR);
    expect(content).toContain("Last evaluated: Fail");
    expect(content).toContain("failing since 3 hours ago");
    expect(content).not.toContain("—");
    expect(content).not.toContain("Failing since");
    const failingSince = Array.from(latest().querySelectorAll(".last-evaluated time")).map((t) => t.getAttribute("datetime"));
    expect(failingSince).toContain(STARTED.A);
  });

  it("interrupted: 20.00%, expected < 5%, and Failing since run A", async () => {
    await renderEmail();
    const content = text(latest());
    expect(content).toContain("20.00%");
    expect(content).toContain("expected < 5%");
    expect(content).toContain("Failing since 3 hours ago");
    expect(latest().querySelector(".since time")?.getAttribute("datetime")).toBe(STARTED.A);
  });

  it("uses the same wording as the overview's row, word for word", async () => {
    await renderOverview(beforeF);
    const row = rowFor(EMAIL);
    const overviewResult = text(row.querySelector(".cell-result") ?? row);
    const overviewWhen = text(row.querySelector(".cell-when") ?? row);
    cleanup();
    await renderCheck(EMAIL, {
      check: ok(detailOf(beforeF, EMAIL)),
      history: ok(emailHistoryBeforeF),
      runs: ok(beforeF.runs),
    });
    const detail = section("Latest result");
    expect(text(detail.querySelector(".result") ?? detail)).toBe(overviewResult);
    expect(text(detail.querySelector(".when") ?? detail)).toBe(overviewWhen);
  });

  it("says 'Not in the latest run' when the result is not from the newest run", async () => {
    const id = "41e58afff9c48a46";
    await renderCheck(id, { check: ok(detailOf(recorded, id)), history: ok(recordedHistory(id)), runs: ok(recorded.runs) });
    expect(text(latest())).toContain("Not in the latest run");
  });

  it("edited-pending: the rule reads < 25%, and the latest result names the rule that judged it", async () => {
    await renderCheck(EDITED_ID, { check: ok(editedPending.check), history: ok(editedPending.history) });
    expect(text(section("Rule"))).toContain("Expected < 25%");
    expect(text(section("Rule"))).toContain("No run has used this rule yet");
    const content = text(latest());
    expect(content).toContain("20.00%");
    expect(content).toContain("Judged by an earlier rule, missing_percent(email) < 15%");
  });

  it("shows no pending note when the newest result was judged by the current rule", async () => {
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(edited.history) });
    expect(document.querySelector("[data-note]")).toBeNull();
  });
});

describe("D5: the chart plots recorded values and marks recorded outcomes", () => {
  it("interrupted b1ceb8262d8b5441: three fail marks at 20, E in its own lane, never at 0", async () => {
    await renderEmail();
    const values = marks("value");
    expect(values.map((m) => m.getAttribute("data-outcome"))).toEqual(["fail", "fail", "fail"]);
    const errors = marks("error");
    expect(errors).toHaveLength(1);
    expect(errors[0]?.getAttribute("data-outcome")).toBe("error");
    expect(errors[0]?.querySelector("rect.icon-fill")).not.toBeNull(); // the error shape: a square
    const lanes = Array.from(chart().querySelectorAll(".chart__lane-label")).map((l) => l.textContent);
    expect(lanes).toEqual(["Could not evaluate"]);
    const zero = chart().querySelector('.chart__axis--y text:first-child');
    expect(zero?.textContent).toBe("0%");
    const plotBottom = Math.max(...Array.from(chart().querySelectorAll(".chart__grid line")).map((l) => Number(l.getAttribute("y1"))));
    const errorY = Number(/translate\([\d.]+ ([\d.]+)\)/.exec(errors[0]?.getAttribute("transform") ?? "")?.[1]);
    expect(errorY).toBeGreaterThan(plotBottom);
    const key = within(screen.getByRole("list", { name: "Chart key" }));
    expect(key.getByText("Could not evaluate")).toBeTruthy();
  });

  it("breaks the line at E: A to B only", async () => {
    await renderEmail();
    const paths = Array.from(chart().querySelectorAll(".chart__line"));
    expect(paths).toHaveLength(1);
    expect((paths[0]?.getAttribute("d") ?? "").match(/[ML]/g)).toEqual(["M", "L"]);
  });

  it("interrupted 32c8f939b90f6367: three pass marks and one error mark", async () => {
    const id = "32c8f939b90f6367";
    await renderCheck(id, { check: ok(detailOf(interrupted, id)), history: ok(rowsHistory) });
    expect(marks("value").map((m) => m.getAttribute("data-outcome"))).toEqual(["pass", "pass", "pass"]);
    expect(marks("error")).toHaveLength(1);
  });
});

describe("D6: the threshold band, rendered", () => {
  it("interrupted: the region from 5 up is shaded, a line at 5 is labelled < 5%", async () => {
    await renderEmail();
    const band = chart().querySelector(".chart__band--fail");
    const line = chart().querySelector(".chart__boundary--fail");
    expect(band).not.toBeNull();
    expect(Number(band?.getAttribute("y")) + Number(band?.getAttribute("height"))).toBeCloseTo(Number(line?.getAttribute("y1")), 1);
    const labels = Array.from(chart().querySelectorAll('[data-label="boundary"]')).map((l) => l.textContent);
    expect(labels).toEqual(["< 5%"]);
  });

  it("recorded 000f8d0048744bfb (= 0, fail at 1): the mark sits in a shaded fail region, the line at 0", async () => {
    const id = "000f8d0048744bfb";
    await renderCheck(id, { check: ok(detailOf(recorded, id)), history: ok(recordedHistory(id)) });
    const band = chart().querySelector(".chart__band--fail");
    const line = chart().querySelector(".chart__boundary--fail");
    const [mark] = marks("value");
    const markY = Number(/translate\([\d.]+ ([\d.]+)\)/.exec(mark?.getAttribute("transform") ?? "")?.[1]) + 6;
    const top = Number(band?.getAttribute("y"));
    const bottom = top + Number(band?.getAttribute("height"));
    expect(markY).toBeGreaterThanOrEqual(top);
    expect(markY).toBeLessThanOrEqual(bottom);
    const zeroTick = Array.from(chart().querySelectorAll(".chart__axis--y text")).find((t) => t.textContent === "0");
    expect(Number(line?.getAttribute("y1"))).toBe(Number(zeroTick?.getAttribute("y")));
  });

  it("an off-range boundary is an edge label, and the rule's text stays next to the chart", async () => {
    const id = "cd3e8103b4318809";
    await renderCheck(id, { check: ok(detailOf(recorded, id)), history: ok(recordedHistory(id)) });
    const off = Array.from(chart().querySelectorAll('[data-label="off-range"]')).map((l) => l.textContent);
    expect(off).toEqual(["10,000 above"]);
    expect(text(document.querySelector(".chart") ?? document.body)).toContain("between 1 and 10000");
  });
});

describe("D7: a rule change under an explicit id", () => {
  it("edited: one marker, labelled with both recorded rules, between the runs", async () => {
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(edited.history) });
    expect(chart().querySelectorAll(".chart__marker")).toHaveLength(1);
    expect(text(chart().querySelector(".chart__marker") ?? chart())).toBe("Rule changed");
    const caption = text(document.querySelector("[data-rule-change]") ?? document.body);
    expect(caption).toMatch(/^Rule changed between runs .+ and .+: from missing_percent\(email\) < 5% to missing_percent\(email\) < 15%\.$/);
    const times = Array.from(document.querySelectorAll("[data-rule-change] time")).map((t) => t.getAttribute("dateTime"));
    expect(times).toEqual([STARTED.A, "2026-09-26T07:30:00.000000+00:00"]);
  });

  it("edited: the band and the < 15% line start at the marker; A has none", async () => {
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(edited.history) });
    const markerX = Number(chart().querySelector(".chart__marker line")?.getAttribute("x1"));
    const band = chart().querySelector(".chart__band--fail");
    expect(Number(band?.getAttribute("x"))).toBe(markerX);
    expect(Number(chart().querySelector(".chart__boundary")?.getAttribute("x1"))).toBe(markerX);
    const a = marks("value").find((m) => m.getAttribute("data-index") === "1");
    const ax = Number(/translate\(([\d.]+)/.exec(a?.getAttribute("transform") ?? "")?.[1]) + 6;
    expect(ax).toBeLessThan(markerX);
  });

  it("edited: the table marks A's recorded rule as different; C's row does not repeat it", async () => {
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(edited.history) });
    const [c, a] = historyRows();
    expect(text(a ?? document.body)).toContain("Different rule missing_percent(email) < 5%");
    expect(c?.querySelector("[data-other-rule]")).toBeNull();
    expect(text(c ?? document.body)).not.toContain("missing_percent(email) < 15%");
  });

  it("edited-pending: no band and no line; the rule and the not-yet-used note are beside the chart", async () => {
    await renderCheck(EDITED_ID, { check: ok(editedPending.check), history: ok(editedPending.history) });
    expect(chart().querySelectorAll(".chart__band, .chart__boundary")).toHaveLength(0);
    const figure = text(document.querySelector(".chart") ?? document.body);
    expect(figure).toContain("< 25%");
    expect(figure).toContain("No run has used the current rule yet");
    const caption = text(document.querySelector("[data-rule-change]") ?? document.body);
    expect(caption).toContain("from missing_percent(email) < 5% to missing_percent(email) < 15%");
    expect(document.querySelectorAll("[data-rule-change]")).toHaveLength(1);
  });
});

describe("D8: marks follow the recorded outcome", () => {
  it("draws A as pass although 20 is inside today's failing region", async () => {
    const { threeRules } = await import("./fixtures/detail");
    await renderCheck(EDITED_ID, { check: ok(threeRules.check), history: ok(threeRules.history) });
    const byIndex = Object.fromEntries(marks("value").map((m) => [m.getAttribute("data-index"), m.getAttribute("data-outcome")]));
    expect(byIndex).toEqual({ "0": "fail", "1": "fail", "2": "pass" });
  });
});

describe("D9: a failure with no value", () => {
  it.each(["no value to evaluate", "no timestamps in scope"])("'%s': a fail mark in the No value lane, the message in the table", async (message) => {
    const empty = entry(emailSummary, "F", { outcome: "fail", value: null, display_value: "—", message });
    await renderEmail(interrupted, page([empty, ...emailHistory.items.slice(1)]));
    const lane = marks("no-value");
    expect(lane.map((m) => m.getAttribute("data-outcome"))).toEqual(["fail"]);
    const lanes = Array.from(chart().querySelectorAll(".chart__lane-label")).map((l) => l.textContent);
    expect(lanes).toEqual(["Could not evaluate", "No value"]);
    const key = screen.getByRole("list", { name: "Chart key" });
    expect(within(key).getByText("Fail: no value measured")).toBeTruthy();
    expect(within(key).getByText("Could not evaluate")).toBeTruthy();
    const [row] = historyRows();
    expect(text(row ?? document.body)).toContain(message);
    expect(text(row ?? document.body)).toContain("No value measured");
    expect(text(row ?? document.body)).not.toContain("—");
  });

  it("a skipped entry has its own shape and the name Skipped", async () => {
    const skipped = entry(emailSummary, "F", { outcome: "skipped", value: null, display_value: "—" });
    await renderEmail(interrupted, page([skipped, ...emailHistory.items.slice(1)]));
    expect(marks("no-value").map((m) => m.getAttribute("data-outcome"))).toEqual(["skipped"]);
    expect(within(screen.getByRole("list", { name: "Chart key" })).getByText("Skipped")).toBeTruthy();
  });
});

describe("D10: the y-axis, rendered", () => {
  it("titles the axis with the metric and its unit", async () => {
    await renderEmail();
    expect(document.querySelector(".chart__axis-title")?.textContent).toBe("missing_percent (%)");
  });

  it("draws a negative freshness below 0", async () => {
    const id = "a81b0374b0b04f06";
    const check = detailOf(recorded, id);
    const future = [
      entry(check, "B", { value: -21600, display_value: "-6h", outcome: "pass" }),
      entry(check, "A", { value: -25200, display_value: "-7h", outcome: "pass" }),
    ];
    await renderCheck(id, { check: ok(check), history: ok(page(future)) });
    const zero = Array.from(chart().querySelectorAll(".chart__axis--y text")).find((t) => t.textContent === "0s");
    const zeroY = Number(zero?.getAttribute("y"));
    for (const m of marks("value")) {
      const y = Number(/translate\([\d.]+ ([\d.]+)\)/.exec(m.getAttribute("transform") ?? "")?.[1]) + 6;
      expect(y).toBeGreaterThan(zeroY);
    }
  });
});

describe("D11: the chart is accessible", () => {
  it("is an img labelled by its title and described by its summary", async () => {
    await renderEmail();
    const svg = chart();
    expect(svg.getAttribute("role")).toBe("img");
    const [titleId, descId] = (svg.getAttribute("aria-labelledby") ?? "").split(" ");
    expect(document.getElementById(titleId ?? "")?.tagName.toLowerCase()).toBe("title");
    const desc = document.getElementById(descId ?? "")?.textContent ?? "";
    for (const part of ["4 results", "3 fail", "1 could not evaluate", "20.00%", "< 5%", "14:55:50", "14:56:45"]) {
      expect(desc).toContain(part);
    }
    expect(screen.getByRole("img", { name: /History of missing_percent\(email\) < 5%/ })).toBe(svg);
  });

  it("has one table row per entry the chart draws", async () => {
    await renderEmail();
    expect(historyRows()).toHaveLength(emailHistory.items.length);
    expect(marks()).toHaveLength(emailHistory.items.length);
  });

  it("shows a tooltip on keyboard focus and moves with the arrow keys; value first, zone stated", async () => {
    await renderEmail();
    const group = screen.getByRole("group", { name: /History chart/ });
    expect(group.tabIndex).toBe(0);
    act(() => {
      group.focus();
    });
    const tip = (): string[] => Array.from(chart().querySelectorAll(".chart__tooltip text")).map((t) => t.textContent ?? "");
    expect(tip()[0]).toBe("20.00%");
    expect(tip().join(" ")).toMatch(/14:56:45 (GMT\+8|SGT)/);
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(tip()[0]).toBe("Could not evaluate");
    expect(tip().join(" ")).toContain("IO Error");
    expect(chart().querySelector(".chart__crosshair")).not.toBeNull();
    fireEvent.keyDown(group, { key: "Escape" });
    expect(chart().querySelector(".chart__tooltip")).toBeNull();
  });

  it("shows the tooltip on pointer hover", async () => {
    await renderEmail();
    const hits = chart().querySelectorAll(".chart__hit");
    expect(hits).toHaveLength(4);
    fireEvent.pointerEnter(hits[0] as Element);
    expect(chart().querySelector(".chart__tooltip text")?.textContent).toBe("20.00%");
  });

  it("states the time zone on the x-axis and in the table", async () => {
    await renderEmail();
    expect(chart().querySelector(".chart__time-note")?.textContent).toMatch(/times in (GMT\+8|SGT)/);
    expect(document.querySelector(".history-table__caption")?.textContent).toMatch(/Times in (GMT\+8|SGT)/);
  });

  it("lays its right-hand labels out without overlapping", async () => {
    const detail = detailOf(interrupted, EMAIL);
    // A value right at the threshold: the latest label and the boundary label want the same place.
    const near = page(emailHistory.items.map((e) => (e.value === null ? e : { ...e, value: 5.2, display_value: "5.20%" })));
    await renderCheck(EMAIL, { check: ok(detail), history: ok(near) });
    const ys = Array.from(chart().querySelectorAll(".chart__right text"))
      .map((t) => Number(t.getAttribute("y")))
      .sort((a, b) => a - b);
    expect(ys.length).toBe(2);
    for (let i = 1; i < ys.length; i += 1) expect((ys[i] ?? 0) - (ys[i - 1] ?? 0)).toBeGreaterThanOrEqual(14);
  });

  it("keeps the streak and rule-change labels on separate rows (D19 with D7)", async () => {
    await renderCheck(EDITED_ID, { check: ok(edited.check), history: ok(edited.history) });
    const streakY = Number(chart().querySelector(".chart__streak text")?.getAttribute("y"));
    const markerY = Number(chart().querySelector(".chart__marker text")?.getAttribute("y"));
    expect(Math.abs(streakY - markerY)).toBeGreaterThanOrEqual(14);
  });
});

describe("D12: the history table", () => {
  it("interrupted: 4 rows, newest first, with time, badge, value, message and trigger", async () => {
    await renderEmail();
    const rowsShown = historyRows();
    expect(rowsShown.map((r) => r.dataset.runId)).toEqual([RUN_ID.F, RUN_ID.E, RUN_ID.B, RUN_ID.A]);
    const [f, e] = rowsShown;
    expect(f?.querySelector("time")?.getAttribute("datetime")).toBe(STARTED.F);
    expect(text(f ?? document.body)).toContain("20.00%");
    expect(text(f ?? document.body)).toContain("expected < 5%");
    expect(text(f ?? document.body)).toContain("cli");
    expect(within(f ?? document.body).getByText("Fail")).toBeTruthy();
    expect(text(e ?? document.body)).toContain("Could not evaluate");
    expect(text(e ?? document.body)).toContain(IO_ERROR);
    expect(text(e ?? document.body)).not.toContain("—");
  });

  it("heads the value column Value, before Message", async () => {
    await renderEmail();
    const headers = within(screen.getByRole("table")).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers.indexOf("Value")).toBeLessThan(headers.indexOf("Message"));
    expect(headers.indexOf("Value")).toBeGreaterThan(-1);
  });

  it("shows messages verbatim: no reformatted timestamps, no reformatted zero", async () => {
    const id = "41e58afff9c48a46";
    await renderCheck(id, { check: ok(detailOf(recorded, id)), history: ok(recordedHistory(id)) });
    const message = recorded.checks.items.find((c) => c.id === id)?.latest?.message ?? "";
    expect(message).toContain("newest 2026-09-23T06:55:49.000000+00:00");
    expect(text(historyRows()[0] ?? document.body)).toContain(message);
  });
});

describe("D13: long histories", () => {
  it("says it shows the latest 200, and loads older results into the chart and the table", async () => {
    const many = Array.from({ length: 200 }, (_, i) =>
      entry(emailSummary, "A", {
        run_id: `r${String(i).padStart(31, "0")}`,
        started_at: new Date(Date.parse(STARTED.F) - i * 60_000).toISOString(),
        outcome: "fail",
        value: 20,
        display_value: "20.00%",
      }),
    );
    const older = entry(emailSummary, "A", {
      run_id: "older000000000000000000000000000",
      started_at: "2026-09-25T00:00:00.000000+00:00",
      outcome: "pass",
      value: 1,
      display_value: "1.00%",
    });
    await renderCheck(EMAIL, {
      check: ok(detailOf(interrupted, EMAIL)),
      history: ok(page(many, "CURSOR/1")),
      older: { "CURSOR/1": ok(page([older])) },
    });
    expect(text(document.querySelector('[data-caption="partial"]') ?? document.body)).toBe(
      "Shows the latest 200 results, not all of them.",
    );
    expect(historyRows()).toHaveLength(200);
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fireEvent.click(screen.getByRole("button", { name: "Load older results" }));
    await vi.waitFor(() => {
      expect(historyRows()).toHaveLength(201);
    });
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain(olderUrl(EMAIL, "CURSOR/1"));
    expect(olderUrl(EMAIL, "CURSOR/1")).toBe("/api/v1/checks/b1ceb8262d8b5441/history?limit=200&cursor=CURSOR%2F1");
    expect(marks()).toHaveLength(201);
    expect(document.querySelector('[data-caption="partial"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "Load older results" })).toBeNull();
  });

  it("has no partial caption and no load button when the history is complete", async () => {
    await renderEmail();
    expect(document.querySelector('[data-caption="partial"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "Load older results" })).toBeNull();
  });
});

describe("D14: one load/refresh hook", () => {
  it("refresh re-fetches /project, /checks/{id}, /history, /runs and /sql, and drops older pages", async () => {
    const older = entry(emailSummary, "A", { run_id: "older000000000000000000000000000", started_at: "2026-09-25T00:00:00.000000+00:00" });
    await renderCheck(EMAIL, {
      check: ok(detailOf(interrupted, EMAIL)),
      history: ok(page(emailHistory.items, "C1")),
      older: { C1: ok(page([older])) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load older results" }));
    await vi.waitFor(() => {
      expect(historyRows()).toHaveLength(5);
    });
    const second = stubCheckServer(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(page(emailHistory.items, "C1")) });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    const urls = checkUrls(EMAIL);
    expect(second.mock.calls.map((c) => String(c[0])).sort()).toEqual([urls.check, urls.history, urls.project, urls.runs, urls.sql].sort());
    expect(historyRows()).toHaveLength(4);
  });

  it("drops an older-results answer that lands after a refresh", async () => {
    let release: (r: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => {
      release = resolve;
    });
    await renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(page(emailHistory.items, "C1")) });
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL) => Promise<Response>;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => (String(input) === olderUrl(EMAIL, "C1") ? slow : base(input))),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load older results" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    await act(async () => {
      release(new Response(JSON.stringify(page([entry(emailSummary, "A", { run_id: "late" })])), { status: 200 }));
      await slow;
    });
    expect(historyRows()).toHaveLength(4);
    expect(historyRows().map((r) => r.dataset.runId)).not.toContain("late");
  });

  it("Load older is disabled while a refresh is in flight, and follows the new cursor after it", async () => {
    let release: (r: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const urls = checkUrls(EMAIL);
    await renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(page(emailHistory.items, "C1")) });
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (String(input) === urls.history ? slow : base(input))));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    const button = screen.getByRole<HTMLButtonElement>("button", { name: "Load older results" });
    expect(button.disabled).toBe(true);
    await act(async () => {
      release(new Response(JSON.stringify(page(emailHistory.items, "C2")), { status: 200 }));
      await slow;
    });
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    const after = stubCheckServer(EMAIL, {
      check: ok(detailOf(interrupted, EMAIL)),
      history: ok(page(emailHistory.items, "C2")),
      older: { C2: ok(page([])) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load older results" }));
    await vi.waitFor(() => {
      expect(after.mock.calls.map((c) => String(c[0]))).toContain(olderUrl(EMAIL, "C2"));
    });
  });

  it("drops a slow first answer that arrives after a refresh", async () => {
    let release: (r: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const urls = checkUrls(EMAIL);
    await renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(emailHistory) });
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (String(input) === urls.history ? slow : base(input))));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    stubCheckServer(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(page(emailHistory.items.slice(0, 2))) });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(historyRows()).toHaveLength(2);
    });
    await act(async () => {
      release(new Response(JSON.stringify(emailHistory), { status: 200 }));
      await slow;
    });
    expect(historyRows()).toHaveLength(2);
  });
});

describe("D15: failures and unknown checks", () => {
  it("404 for an id nobody knows: says so, names the id as text, links to the overview, no chart or status", async () => {
    await renderCheck("no-such-check", { check: notFound(), history: notFound() });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Check not found");
    expect(screen.getByText("no-such-check", { selector: "code" })).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /overview/ }).some((a) => a.getAttribute("href") === "/")).toBe(true);
    expect(document.querySelector("svg.chart__svg")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(document.querySelector(".badge")).toBeNull();
    expect(document.title).toBe("Check not found · tablewatch");
  });

  it("503 from /history: keeps the header and identity, shows the message with a retry, no chart and no 'no results'", async () => {
    await renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: UNAVAILABLE });
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("missing_percent(email) < 5%");
    const alert = screen.getByRole("alert");
    expect(text(alert)).toContain("results store: unavailable — see the server log");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(document.querySelector("svg.chart__svg")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(/no results/i)).toBeNull();
  });

  it("503 from /checks/{id}: no identity, no chart, the message with a retry", async () => {
    await renderCheck(EMAIL, { check: UNAVAILABLE, history: ok(emailHistory) });
    expect(text(screen.getByRole("alert"))).toContain("results store: unavailable");
    expect(document.querySelector("svg.chart__svg")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(document.querySelector(".badge")).toBeNull();
  });

  it("recovers on Try again", async () => {
    await renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: UNAVAILABLE });
    stubCheckServer(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(emailHistory) });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("table");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a loaded check with no history: identity, rule, 'No result recorded', 'No results recorded yet'", async () => {
    const id = "e41cf32f07f328c3";
    const check: CheckDetail = {
      ...(renamedState.checks.items.find((c) => c.id === id) ?? detailOf(recorded, EMAIL)),
      rule: { expect: { kind: "compare", op: "<", value: 10, text: "< 10%" }, warn: null, fail: null },
    };
    await renderCheck(id, { check: ok(check), history: ok(page([])) });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("missing_percent(email) < 10%");
    expect(text(section("Rule"))).toContain("< 10%");
    expect(text(section("Latest result"))).toContain("No result recorded");
    expect(text(section("History"))).toBe("HistoryNo results recorded yet.");
    expect(screen.queryByText(/pass/i)).toBeNull();
    expect(document.querySelector("svg.chart__svg")).toBeNull();
  });

  it("an id no longer loaded but with history: says so, shows the table and a chart without a band", async () => {
    await renderCheck(EMAIL, { check: notFound(), history: ok(emailHistory) });
    expect(text(document.querySelector('[data-note="not-loaded"]') ?? document.body)).toContain(
      "no longer in the loaded check files",
    );
    expect(historyRows()).toHaveLength(4);
    expect(chart().querySelectorAll(".chart__band, .chart__boundary")).toHaveLength(0);
    expect(marks("value")).toHaveLength(3);
    expect(document.querySelector(".chart__axis-title")?.textContent).toBe("missing_percent (%)");
  });

  it("an id no longer loaded whose results measured several metrics: the table alone", async () => {
    await renderCheck(EDITED_ID, { check: notFound(), history: ok(metricChangedBack.history) });
    expect(document.querySelector("svg.chart__svg")).toBeNull();
    expect(document.querySelector('[data-caption="not-charted"]')).not.toBeNull();
    expect(historyRows()).toHaveLength(4);
  });
});

describe("D16: data renders as text", () => {
  it("creates no element from a name, a message or an expression, in the page, chart and tooltip", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    const NAME = "<img src=x onerror=alert(1)>";
    const MESSAGE = "<script>alert(1)</script>";
    const EXPR = "row_count > 0 <b>x</b>";
    const detail: CheckDetail = { ...detailOf(interrupted, EMAIL), name: NAME };
    const hostile: HistoryEntry[] = [
      { ...(emailHistory.items[0] as HistoryEntry), message: MESSAGE },
      { ...(emailHistory.items[1] as HistoryEntry), expression: EXPR, message: MESSAGE },
      ...emailHistory.items.slice(2),
    ];
    await renderCheck(EMAIL, { check: ok(detail), history: ok(page(hostile)) });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(NAME);
    expect(chart().querySelector("title")?.textContent).toBe(`History of ${NAME}`);
    expect(text(document.querySelector("[data-rule-change]") ?? document.body)).toContain(EXPR);
    expect(text(screen.getByRole("table"))).toContain(MESSAGE);
    const group = screen.getByRole("group", { name: /History chart/ });
    act(() => {
      group.focus();
    });
    expect(text(chart().querySelector(".chart__tooltip") ?? chart())).toContain(MESSAGE);
    expect(document.querySelectorAll("img, script, b, foreignObject")).toHaveLength(0);
    expect(document.title).toBe(`${NAME} · tablewatch`);
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("D17: no new dependencies", () => {
  it("runtime dependencies are exactly react and react-dom", () => {
    const pkg = JSON.parse(packageJsonText) as { dependencies: Record<string, string> };
    expect(Object.keys(pkg.dependencies).sort()).toEqual(["react", "react-dom"]);
  });
});

describe("D18: the overview is otherwise unchanged", () => {
  it("keeps each row's text: the link holds the name, nothing else changes", async () => {
    await renderOverview(recorded);
    const row = rowFor("32867fbe86f483f3");
    expect(within(row).getByRole("link").textContent).toBe("Order volume");
    expect(text(row.querySelector(".cell-check") ?? row)).toBe(
      "Order volumerow_count | warn when < 100 | fail when = 0sales.orderschecks/sales/orders.yml:5:5",
    );
  });
});

describe("D19: the chart marks where the current streak began", () => {
  it("interrupted: from run A, with the overview's 'Failing since' wording, E inside the span", async () => {
    await renderEmail();
    const streak = chart().querySelector(".chart__streak");
    expect(text(streak ?? chart())).toMatch(/^Failing since Sep 26, 2026, 14:55:50 (GMT\+8|SGT)$/);
    const d = streak?.querySelector("path")?.getAttribute("d") ?? "";
    const [x0, x1] = [...d.matchAll(/[MH]([\d.]+)/g)].map((m) => Number(m[1]));
    const error = marks("error")[0];
    const ex = Number(/translate\(([\d.]+)/.exec(error?.getAttribute("transform") ?? "")?.[1]) + 6;
    expect(ex).toBeGreaterThan(x0 ?? Infinity);
    expect(ex).toBeLessThan(x1 ?? -Infinity);
    expect(within(screen.getByRole("list", { name: "Chart key" })).getByText("The current streak")).toBeTruthy();
  });
});

describe("D20: a value measured by another metric is not plotted", () => {
  it("plots N, C and A, not M; says so; the table lists M; markers at C→M and M→N", async () => {
    await renderCheck(EDITED_ID, { check: ok(metricChangedBack.check), history: ok(metricChangedBack.history) });
    expect(marks("value")).toHaveLength(3);
    expect(marks()).toHaveLength(3);
    expect(text(document.querySelector('[data-caption="other-metric"]') ?? document.body)).toBe(
      "1 result measured a different metric (missing_count) and is not plotted. The table lists it.",
    );
    const m = historyRows()[1];
    expect(text(m ?? document.body)).toContain("1");
    expect(text(m ?? document.body)).toContain("Different rule missing_count(email) = 0");
    expect(text(m ?? document.body)).toContain("Not on the chart: measured by missing_count");
    expect(chart().querySelectorAll(".chart__marker")).toHaveLength(3);
    const captions = Array.from(document.querySelectorAll("[data-rule-change]")).map((c) => text(c));
    expect(captions[1]).toContain("to missing_count(email) = 0");
    expect(captions[2]).toContain("from missing_count(email) = 0");
    expect(captions[0]).toMatch(/^Rule change 1: between runs/);
    expect(Array.from(chart().querySelectorAll(".chart__marker text")).map((t) => t.textContent)).toEqual([
      "Rule change 1",
      "Rule change 2",
      "Rule change 3",
    ]);
  });
});
