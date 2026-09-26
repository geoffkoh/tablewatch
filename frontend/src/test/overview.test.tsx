/**
 * The overview page, scenario by scenario (spec 003, O1–O11). Every API
 * response is a fixture typed against the generated contract.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import {
  allPassBrokenState,
  allPassButOneUnknownState,
  allPassState,
  brokenState,
  brokenYamlState,
  emptyState,
  mapLatest,
  noRunsState,
  renamedState,
  skippedState,
  warningsOnlyState,
} from "./fixtures/derived";
import { beforeF, interrupted, recorded, RUN_ID, STARTED } from "./fixtures/states";
import {
  CLOCK,
  renderOverview,
  rowFor,
  rows,
  setClock,
  statuses,
  stubServer,
  text,
  tile,
  URLS,
} from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

const repeat = (status: string, n: number): string[] => Array.from({ length: n }, () => status);

describe("O1: problems first", () => {
  it("orders recorded as 6 fail, 2 warn, 10 pass", async () => {
    await renderOverview(recorded);
    expect(statuses()).toEqual([...repeat("fail", 6), ...repeat("warn", 2), ...repeat("pass", 10)]);
  });

  it("keeps the API's order within a status", async () => {
    await renderOverview(recorded);
    const apiFails = recorded.checks.items.filter((c) => c.latest?.outcome === "fail").map((c) => c.id);
    const shown = rows()
      .filter((r) => r.dataset.status === "fail")
      .map((r) => r.dataset.checkId);
    expect(shown).toEqual(apiFails);
  });

  it("orders A, B, E as 4 fail, 5 error, 2 warn, 7 pass", async () => {
    await renderOverview(beforeF);
    expect(statuses()).toEqual([
      ...repeat("fail", 4),
      ...repeat("error", 5),
      ...repeat("warn", 2),
      ...repeat("pass", 7),
    ]);
  });

  it("orders every status: fail, error, warn, no result, skipped, pass", async () => {
    const mixed = mapLatest(beforeF, (c) => {
      if (c.id === "cd3e8103b4318809" && c.latest !== null) return { ...c.latest, outcome: "skipped" };
      if (c.id === "8b9c5af854ba2a5f") return null;
      return c.latest;
    });
    await renderOverview(mixed);
    const order = statuses().filter((s, i, all) => all.indexOf(s) === i);
    expect(order).toEqual(["fail", "error", "warn", "none", "skipped", "pass"]);
  });
});

describe("O2: error and fail never look alike", () => {
  it("differs in label and icon", async () => {
    await renderOverview(beforeF);
    const fail = rowFor("fc9cc3088acaf77a");
    const error = rowFor("b1ceb8262d8b5441");
    expect(within(fail).getByText("Fail")).toBeTruthy();
    expect(within(error).getByText("Error")).toBeTruthy();
    const failIcon = within(fail).getAllByRole("img")[0];
    const errorIcon = within(error).getAllByRole("img")[0];
    expect(failIcon?.getAttribute("aria-label")).toBe("Data failed the check");
    expect(errorIcon?.getAttribute("aria-label")).toBe("Could not evaluate");
    expect(failIcon?.getAttribute("class")).not.toBe(errorIcon?.getAttribute("class"));
    expect(fail.className).not.toBe(error.className);
  });

  it("says the error row could not be evaluated, shows the message and hides the dash", async () => {
    await renderOverview(beforeF);
    const error = rowFor("b1ceb8262d8b5441");
    expect(text(error)).toMatch(/could not evaluate/i);
    expect(text(error)).toContain('IO Error: Cannot open database "/opt/dq/retail/retail.duckdb"');
    expect(text(error)).not.toContain("—");
  });

  it("counts errors apart from failures, with 'could not evaluate'", async () => {
    await renderOverview(beforeF);
    expect(text(tile("fail"))).toContain("4 failing");
    expect(text(tile("error"))).toContain("5 errors");
    expect(text(tile("error"))).toMatch(/could not evaluate/i);
    expect(text(screen.getByRole("region", { name: "Summary" }))).not.toContain("9 failing");
  });

  it("every error row carries 'could not evaluate'", async () => {
    await renderOverview(beforeF);
    const errors = rows().filter((r) => r.dataset.status === "error");
    expect(errors).toHaveLength(5);
    for (const row of errors) expect(text(row)).toMatch(/could not evaluate/i);
  });

  it("says what the data last showed (P7), and how many errors were failing", async () => {
    await renderOverview(beforeF);
    const wasFailing = text(rowFor("b1ceb8262d8b5441"));
    expect(wasFailing).toContain("Last evaluated: Fail");
    expect(wasFailing).toContain("failing since 3 hours ago");
    const wasPassing = text(rowFor("32c8f939b90f6367"));
    expect(wasPassing).toContain("Last evaluated: Pass");
    expect(wasPassing).not.toMatch(/failing since/i);
    expect(text(tile("error"))).toContain("2 were failing");
    expect(text(tile("fail"))).toContain("4 failing");
  });
});

describe("O3: no result is unknown, never healthy", () => {
  it("labels the row 'No result recorded' with its own icon, after warn and before pass", async () => {
    await renderOverview(renamedState);
    const row = rowFor("e41cf32f07f328c3");
    expect(within(row).getAllByText("No result recorded").length).toBeGreaterThan(0);
    const icon = within(row).getAllByRole("img")[0];
    expect(icon?.getAttribute("aria-label")).toBe("Unknown: never recorded");
    expect(icon?.getAttribute("class")).not.toContain("pass");
    expect(row.className).not.toContain("pass");
    const order = statuses();
    expect(order.indexOf("none")).toBeGreaterThan(order.lastIndexOf("warn"));
    expect(order.indexOf("none")).toBeLessThan(order.indexOf("pass"));
  });

  it("counts it under no result, counts only loaded checks, and names the scope", async () => {
    await renderOverview(renamedState);
    expect(text(tile("none"))).toContain("1 no result");
    expect(text(tile("fail"))).toContain("5 failing");
    expect(text(tile("pass"))).toContain("10 passing");
    expect(screen.queryByText("b1ceb8262d8b5441")).toBeNull();
    expect(text(screen.getByRole("region", { name: "Summary" }))).toContain(
      "Latest result of each of the 18 checks loaded",
    );
    expect(screen.queryByText(/all checks passing/i)).toBeNull();
  });

  it("shows the all-clear only when every check passes, ok is true and there is a check", async () => {
    await renderOverview(allPassState);
    expect(screen.getByText("All checks passing")).toBeTruthy();
  });

  it.each([
    ["a check has no result", allPassButOneUnknownState],
    ["a check file is broken", allPassBrokenState],
    ["no checks are loaded", emptyState],
  ])("shows no all-clear when %s", async (_, fixture) => {
    await renderOverview(fixture);
    expect(screen.queryByText(/all checks passing/i)).toBeNull();
  });

  it("gives skipped its own label and count, never passing, and the counts add up", async () => {
    await renderOverview(skippedState);
    expect(within(rowFor("cd3e8103b4318809")).getAllByText("Skipped").length).toBeGreaterThan(0);
    expect(text(tile("skipped"))).toContain("1 skipped");
    expect(text(tile("pass"))).toContain("9 passing");
    const summary = screen.getByRole("region", { name: "Summary" });
    const total = Array.from(summary.querySelectorAll(".tile__count")).reduce(
      (sum, el) => sum + Number(el.textContent),
      0,
    );
    expect(total).toBe(18);
  });
});

describe("O4: the age of every latest result", () => {
  it("shows '3 hours ago' with a machine-readable time", async () => {
    await renderOverview(recorded);
    for (const row of rows()) {
      const time = row.querySelector("time");
      expect(time?.textContent).toBe("3 hours ago");
      expect(time?.getAttribute("datetime")).toMatch(/^2026-09-26T06:5\d:\d\d\.000000\+00:00$/);
    }
    const inventory = rowFor("41e58afff9c48a46").querySelector("time");
    expect(inventory?.getAttribute("datetime")).toBe(STARTED.A);
  });

  it("shows the full time in the viewer's zone, with the zone, on hover and focus", async () => {
    await renderOverview(recorded);
    const time = rowFor("fc9cc3088acaf77a").querySelector("time");
    expect(time?.getAttribute("datetime")).toBe("2026-09-26T06:56:12.000000+00:00");
    const full = time?.getAttribute("title") ?? "";
    expect(full).toContain("14:56");
    expect(full).toMatch(/GMT\+8|SGT|\+08:00/);
    expect(time?.getAttribute("data-full")).toBe(full);
    expect(time?.tabIndex).toBe(0);
  });

  it("marks, quietly, the rows not in the latest run", async () => {
    await renderOverview(recorded);
    const marked = rows().filter((r) => text(r).includes("Not in the latest run"));
    expect(marked.map((r) => r.dataset.checkId).sort()).toEqual(
      recorded.checks.items
        .filter((c) => c.dataset === "inventory.products")
        .map((c) => c.id)
        .sort(),
    );
    const note = within(rowFor("41e58afff9c48a46")).getByText("Not in the latest run");
    expect(note.className).toContain("quiet");
    expect(note.querySelector("svg")).toBeNull();
  });

  it("shows a future time as 'just now', never a negative age", async () => {
    setClock("2026-09-26T06:00:00Z");
    await renderOverview(recorded);
    for (const row of rows()) expect(row.querySelector("time")?.textContent).toBe("just now");
  });
});

describe("O5: failing since", () => {
  it("shows both the latest age and the failing-since age from latest.since", async () => {
    setClock("2026-09-26T09:00:05Z");
    const fixture = mapLatest(recorded, (c) =>
      c.id === "fc9cc3088acaf77a" && c.latest !== null
        ? { ...c.latest, started_at: "2026-09-26T06:00:00.000000+00:00", since: "2026-09-19T06:00:00.000000+00:00" }
        : c.latest,
    );
    await renderOverview(fixture);
    const row = text(rowFor("fc9cc3088acaf77a"));
    expect(row).toContain("3 hours ago");
    expect(row).toContain("Failing since 7 days ago");
    expect(row).not.toMatch(/continuously/i);
  });

  it("takes interrupted's failing-since from run A", async () => {
    await renderOverview(interrupted);
    for (const id of ["fc9cc3088acaf77a", "b1ceb8262d8b5441"]) {
      const since = rowFor(id).querySelector(".since time");
      expect(since?.getAttribute("datetime")).toBe(STARTED.A);
      expect(text(rowFor(id))).toContain("Failing since 3 hours ago");
    }
  });

  it("gives an error row a could-not-evaluate age from run E, never 'failing since' for itself", async () => {
    await renderOverview(beforeF);
    const row = rowFor("b1ceb8262d8b5441");
    const since = row.querySelector(".since time");
    expect(since?.getAttribute("datetime")).toBe(STARTED.E);
    expect(text(row.querySelector(".since") ?? row)).toBe("Could not evaluate since 3 hours ago");
    expect(row.querySelector(".cell-when")?.textContent).not.toMatch(/failing since/i);
  });

  it("shows warning since on warn rows, and nothing on pass or no-result rows", async () => {
    await renderOverview(renamedState);
    expect(text(rowFor("41e58afff9c48a46"))).toContain("Warning since");
    expect(rowFor("cd3e8103b4318809").querySelector(".since")).toBeNull();
    expect(rowFor("e41cf32f07f328c3").querySelector(".since")).toBeNull();
  });
});

describe("O6: the project banner and an honest count", () => {
  it("lists the diagnostic and marks the counts incomplete", async () => {
    await renderOverview(brokenState);
    const banner = screen.getByRole("region", { name: "A check file has errors" });
    expect(text(banner)).toContain("checks/sales/orders.yml:11:30");
    expect(text(banner)).toContain("expected a number, found '<'");
    expect(text(banner)).toMatch(/may be missing from this page and from every count/);
    const fail = tile("fail");
    expect(text(fail)).toContain("5 failing");
    const marker = within(fail).getByRole("link", { name: "incomplete" });
    expect(marker.getAttribute("href")).toBe(`#${banner.id}`);
    expect(within(tile("pass")).getByRole("link", { name: "incomplete" })).toBeTruthy();
    expect(text(screen.getByRole("region", { name: "Summary" }))).toContain(
      "Latest result of each of the 17 checks loaded (incomplete)",
    );
  });

  it("never states how many checks are missing (broken-yaml)", async () => {
    await renderOverview(brokenYamlState);
    const banner = screen.getByRole("region", { name: "A check file has errors" });
    expect(text(banner)).toContain("checks/sales/orders.yml:24:1");
    expect(text(banner)).toContain("invalid YAML: expected ',' or ']', but got '<stream end>'");
    expect(text(banner)).not.toMatch(/\d+ checks? (is|are) missing/);
    expect(text(banner)).toMatch(/may be missing/);
    expect(rows()).toHaveLength(9);
    expect(text(tile("fail"))).toContain("2 failing");
    expect(within(tile("fail")).getByRole("link", { name: "incomplete" })).toBeTruthy();
  });

  it("shows neither banner nor marker when ok", async () => {
    await renderOverview(recorded);
    expect(screen.queryByRole("region", { name: /check files? ha(s|ve) errors/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "incomplete" })).toBeNull();
  });

  it("puts warnings in a quiet, collapsible notice when ok", async () => {
    await renderOverview(warningsOnlyState);
    const notice = screen.getByText("1 warning in the check files").closest("details");
    expect(notice).not.toBeNull();
    expect(notice?.open).toBe(false);
    expect(text(notice ?? document.body)).toContain("checks/inventory/products.yml:7:7");
    expect(screen.queryByRole("link", { name: "incomplete" })).toBeNull();
  });

  it("lists warnings under the errors when not ok", async () => {
    const fixture = structuredClone(brokenState);
    fixture.project.diagnostics.push({
      severity: "warning",
      message: "a quiet warning",
      location: { file: "checks/sales/customers.yml", line: 2, column: 3 },
    });
    await renderOverview(fixture);
    const banner = screen.getByRole("region", { name: "A check file has errors" });
    const content = text(banner);
    expect(content.indexOf("Warnings")).toBeGreaterThan(content.indexOf("expected a number"));
    expect(content).toContain("checks/sales/customers.yml:2:3 a quiet warning");
  });
});

describe("O7: when the check files were loaded", () => {
  it("shows the project, the version and the age of loaded_at", async () => {
    await renderOverview(recorded);
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("heading", { level: 1 }).textContent).toBe("retail-example");
    expect(text(header)).toContain(recorded.project.version);
    expect(text(header)).toContain("Check files loaded 3 hours ago");
    const time = header.querySelector("time");
    expect(time?.getAttribute("datetime")).toBe(recorded.project.loaded_at);
    expect(time?.getAttribute("title")).toMatch(/GMT\+8|SGT|\+08:00/);
  });
});

describe("O8: the latest run", () => {
  const panel = (): HTMLElement => screen.getByRole("region", { name: "Latest run" });

  it("shows run B's age, trigger, outcome, own counts and selection", async () => {
    await renderOverview(recorded);
    const content = text(panel());
    expect(content).toContain("3 hours ago");
    expect(content).toContain("cli");
    expect(within(panel()).getByText("Fail")).toBeTruthy();
    expect(content).toContain("This run: 14 checks");
    const counts = within(panel()).getByRole("list", { name: "This run's results" });
    expect(within(counts).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "7 pass",
      "1 warn",
      "6 fail",
      "0 error",
    ]);
    expect(content).toContain("paths: checks/sales");
    expect(panel().querySelector("time")?.getAttribute("datetime")).toBe(STARTED.B);
  });

  it("keeps its counts apart from the summary's", async () => {
    await renderOverview(recorded);
    expect(text(tile("warn"))).toContain("2 warnings");
    expect(within(panel()).getByRole("list", { name: "This run's results" }).textContent).toContain("1 warn");
    expect(text(screen.getByRole("region", { name: "Summary" }))).not.toContain("This run");
  });

  it("says 'all checks' for an empty selection", async () => {
    await renderOverview(interrupted);
    expect(text(panel())).toContain("Selected all checks");
  });

  it("shows run E as could-not-evaluate, not as failed", async () => {
    await renderOverview(beforeF);
    const content = text(panel());
    expect(within(panel()).getByText("Error")).toBeTruthy();
    expect(content).toMatch(/could not evaluate/i);
    expect(content).not.toMatch(/\bfailed\b/i);
    expect(content).toContain("This run: 5 checks");
    expect(content).toContain("5 error");
    expect(content).toContain("paths: checks/sales/customers.yml");
  });

  it("shows every selection key, and unknown keys raw", async () => {
    const fixture = structuredClone(recorded);
    const run = fixture.runs.items[0];
    if (run === undefined) throw new Error("fixture has no run");
    run.selection = { paths: ["checks/sales"], tags: ["pii"], owners: ["sam@example.com"] };
    await renderOverview(fixture);
    const content = text(panel());
    expect(content).toContain("paths: checks/sales");
    expect(content).toContain("tags: pii");
    expect(content).toContain("owners: sam@example.com");
    expect(content).not.toContain("all checks");
  });

  it("names the command when no runs are recorded, and nothing passes", async () => {
    await renderOverview(noRunsState);
    expect(text(panel())).toContain("No runs are recorded for this project yet");
    expect(within(panel()).getByText("tablewatch run")).toBeTruthy();
    expect(statuses()).toEqual(repeat("none", 18));
    expect(text(tile("pass"))).toContain("0 passing");
    expect(screen.queryByText(/all checks passing/i)).toBeNull();
    expect(screen.queryByText("Not in the latest run")).toBeNull();
  });
});

describe("O9: API failures are shown, not blank", () => {
  const unavailable = {
    status: 503,
    body: { error: { code: "store_unavailable", message: "results store: unavailable — see the server log" } },
  };

  it("keeps the header and shows the message, with no counts or list", async () => {
    await renderOverview(recorded, { checks: unavailable });
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("retail-example");
    const alert = screen.getByRole("alert");
    expect(text(alert)).toContain("results store: unavailable — see the server log");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("region", { name: "Summary" })).toBeNull();
    expect(screen.queryByText(/passing|failing/)).toBeNull();
  });

  it("shows a comparable message when the request cannot be made", async () => {
    await renderOverview(recorded, { checks: "network-error" });
    expect(text(screen.getByRole("alert"))).toMatch(/could not reach the tablewatch server/i);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("drops the list when a refresh fails, and recovers on try again", async () => {
    await renderOverview(recorded);
    expect(rows()).toHaveLength(18);
    stubServer(recorded, { checks: unavailable });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("alert");
    expect(screen.queryByRole("table")).toBeNull();
    stubServer(recorded);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("table");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("O10: refresh", () => {
  it("fetches the three endpoints again, and re-renders", async () => {
    const first = stubServer(recorded);
    render(<App path="/" />);
    await screen.findByRole("table");
    expect(first.mock.calls.map((c) => String(c[0])).sort()).toEqual(
      [URLS.checks, URLS.project, URLS.runs].sort(),
    );
    const second = stubServer(beforeF);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(text(tile("error"))).toContain("5 errors");
    });
    expect(second.mock.calls.map((c) => String(c[0])).sort()).toEqual(
      [URLS.checks, URLS.project, URLS.runs].sort(),
    );
  });

  it("does not poll", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    vi.setSystemTime(new Date(CLOCK));
    const fetchMock = stubServer(recorded);
    render(<App path="/" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    const calls = fetchMock.mock.calls.length;
    expect(calls).toBe(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000);
    });
    expect(fetchMock.mock.calls.length).toBe(calls);
  });

  it("drops a slow, older answer that arrives after a newer one", async () => {
    await renderOverview(recorded);
    let release: (r: Response) => void = () => undefined;
    const slow = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === URLS.checks) return slow;
      const body = url === URLS.project ? beforeF.project : beforeF.runs;
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    stubServer(beforeF);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(text(tile("error"))).toContain("5 errors");
    });
    await act(async () => {
      release(new Response(JSON.stringify(recorded.checks), { status: 200 }));
      await slow;
    });
    expect(text(tile("error"))).toContain("5 errors");
  });
});

describe("O11: accessible structure", () => {
  it("uses landmarks, headings, a real table and a keyboard-operable refresh", async () => {
    await renderOverview(recorded);
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByRole("main")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Status",
      "Check",
      "Latest result",
      "When",
    ]);
    const refresh = screen.getByRole("button", { name: "Refresh" });
    expect(refresh.tagName).toBe("BUTTON");
    expect(refresh.getAttribute("type")).toBe("button");
    expect(screen.getByRole("link", { name: "Skip to content" }).getAttribute("href")).toBe("#main");
  });

  it("gives every status icon an accessible name", async () => {
    await renderOverview(beforeF);
    for (const img of screen.getAllByRole("img")) {
      expect(img.getAttribute("aria-label")).toMatch(/\S/);
    }
  });
});

describe("W3: unknown paths", () => {
  // Spec 004 D1 made /checks/<id> a page; a run's page (I-15) is not built yet.
  it("renders page not found with a link to the overview, and requests nothing", () => {
    const fetchMock = stubServer(recorded);
    render(<App path="/runs/b0000000000000000000000000000002" />);
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to the overview" }).getAttribute("href")).toBe("/");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("the fixtures", () => {
  it("match the states the spec names", () => {
    const count = (f: typeof recorded, o: string): number =>
      f.checks.items.filter((c) => (c.latest?.outcome ?? "none") === o).length;
    expect([count(recorded, "pass"), count(recorded, "warn"), count(recorded, "fail")]).toEqual([10, 2, 6]);
    expect([count(beforeF, "pass"), count(beforeF, "fail"), count(beforeF, "error")]).toEqual([7, 4, 5]);
    expect(brokenState.checks.items).toHaveLength(17);
    expect([count(brokenYamlState, "pass"), count(brokenYamlState, "warn"), count(brokenYamlState, "fail")]).toEqual([
      6, 1, 2,
    ]);
    expect(recorded.runs.items[0]?.id).toBe(RUN_ID.B);
  });
});
