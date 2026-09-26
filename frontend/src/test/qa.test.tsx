/**
 * qa-engineer, spec 003 VERIFY: the overview's scenarios at the edges the
 * builder's tests do not reach.
 */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mapLatest } from "./fixtures/derived";
import { beforeF, recorded, STARTED } from "./fixtures/states";
import { CLOCK, renderOverview, rowFor, rows, setClock, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

const unavailable = {
  status: 503,
  body: { error: { code: "store_unavailable", message: "results store: unavailable — see the server log" } },
};

describe("O9 beyond /checks", () => {
  it("keeps the header and shows no counts when /project fails", async () => {
    await renderOverview(recorded, { project: unavailable });
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeTruthy();
    const alert = screen.getByRole("alert");
    expect(text(alert)).toContain("results store: unavailable — see the server log");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("region", { name: "Summary" })).toBeNull();
    expect(screen.queryByText(/passing|failing/)).toBeNull();
  });

  it("shows no list or counts when /runs fails", async () => {
    await renderOverview(recorded, { runs: unavailable });
    expect(text(screen.getByRole("alert"))).toContain("results store: unavailable");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("region", { name: "Summary" })).toBeNull();
  });

  it("explains an error without the envelope", async () => {
    await renderOverview(recorded, { checks: { status: 500, body: "oops" } });
    expect(text(screen.getByRole("alert"))).toContain("500");
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("O5 and P7 at the edges", () => {
  it("an error row whose data last warned says 'warning since', never 'failing since'", async () => {
    const fixture = mapLatest(beforeF, (c) =>
      c.id === "b1ceb8262d8b5441" && c.latest?.last_evaluated
        ? { ...c.latest, last_evaluated: { ...c.latest.last_evaluated, outcome: "warn" } }
        : c.latest,
    );
    await renderOverview(fixture);
    const row = text(rowFor("b1ceb8262d8b5441"));
    expect(row).toContain("Last evaluated: Warn");
    expect(row).toMatch(/warning since/i);
    expect(row).not.toMatch(/failing since/i);
  });

  it("an error row with nothing evaluated before it makes no claim about the data", async () => {
    const fixture = mapLatest(beforeF, (c) =>
      c.id === "b1ceb8262d8b5441" && c.latest ? { ...c.latest, last_evaluated: null } : c.latest,
    );
    await renderOverview(fixture);
    const row = text(rowFor("b1ceb8262d8b5441"));
    expect(row).toMatch(/could not evaluate/i);
    expect(row).not.toMatch(/last evaluated|failing|passing/i);
  });

  it("a since in the future (clock skew) reads 'just now', never negative", async () => {
    const fixture = mapLatest(recorded, (c) =>
      c.id === "fc9cc3088acaf77a" && c.latest
        ? { ...c.latest, since: "2026-09-27T00:00:00.000000+00:00", started_at: "2026-09-27T00:00:00.000000+00:00" }
        : c.latest,
    );
    await renderOverview(fixture);
    const row = text(rowFor("fc9cc3088acaf77a"));
    expect(row).toContain("Failing since just now");
    expect(row).not.toMatch(/-\d/);
  });

  it("a since that is not a timestamp does not break the page", async () => {
    const fixture = mapLatest(recorded, (c) =>
      c.id === "fc9cc3088acaf77a" && c.latest ? { ...c.latest, since: "garbage" } : c.latest,
    );
    await renderOverview(fixture);
    expect(rows()).toHaveLength(18);
    expect(text(rowFor("fc9cc3088acaf77a"))).not.toContain("NaN");
  });
});

describe("O8 and O2 in the latest-run panel", () => {
  it("a run that could not evaluate never shows as Fail or as passing", async () => {
    await renderOverview(beforeF);
    const panel = screen.getByRole("region", { name: "Latest run" });
    expect(within(panel).queryByText("Fail")).toBeNull();
    expect(within(panel).queryByText("Pass")).toBeNull();
    expect(within(panel).getAllByRole("img")[0]?.getAttribute("aria-label")).toBe("Could not evaluate");
  });

  it("a run that did not finish says so", async () => {
    const fixture = structuredClone(recorded);
    const run = fixture.runs.items[0];
    if (run === undefined) throw new Error("fixture has no run");
    run.finished_at = null;
    await renderOverview(fixture);
    expect(text(screen.getByRole("region", { name: "Latest run" }))).toMatch(/did not finish/);
  });

  it("renders selection values and the trigger as text (X4)", async () => {
    const fixture = structuredClone(recorded);
    const run = fixture.runs.items[0];
    if (run === undefined) throw new Error("fixture has no run");
    run.trigger = "<img src=x onerror=alert(1)>";
    run.selection = { "<b>owners</b>": ["<script>alert(1)</script>"] };
    await renderOverview(fixture);
    const panel = screen.getByRole("region", { name: "Latest run" });
    expect(text(panel)).toContain("<img src=x onerror=alert(1)>");
    expect(text(panel)).toContain("<b>owners</b>: <script>alert(1)</script>");
    expect(panel.querySelectorAll("img, script, b")).toHaveLength(0);
  });
});

describe("O6 with several broken files", () => {
  it("names each location and never a number of missing checks", async () => {
    const fixture = structuredClone(recorded);
    fixture.project.ok = false;
    fixture.project.diagnostics = [
      { severity: "error", message: "bad one", location: { file: "checks/a.yml", line: 1, column: 2 } },
      { severity: "error", message: "bad two", location: { file: "checks/b.yml", line: 3, column: 4 } },
    ];
    await renderOverview(fixture);
    const banner = screen.getByRole("region", { name: "Check files have errors" });
    expect(text(banner)).toContain("checks/a.yml:1:2 bad one");
    expect(text(banner)).toContain("checks/b.yml:3:4 bad two");
    expect(text(banner)).not.toMatch(/\d+ checks? (is|are|were) missing/);
    expect(screen.queryByText(/all checks passing/i)).toBeNull();
  });
});

describe("O4: the inventory rows carry run A's time", () => {
  it("uses latest.started_at, not the newest run's", async () => {
    await renderOverview(recorded);
    expect(rowFor("41e58afff9c48a46").querySelector("time")?.getAttribute("datetime")).toBe(STARTED.A);
  });
});
