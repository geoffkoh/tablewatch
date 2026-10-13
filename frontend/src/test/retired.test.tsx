/**
 * Retired checks in the web UI (spec 037, S12 and S13): the explorer's "Show
 * retired" toggle, and a retired check's own page.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { CheckList, CheckListItem, RetiredCheckSummary } from "../api/types";
import {
  EMPTY_QUERY,
  explorerSearch,
  filterRetired,
  isRetired,
  matchesRetiredText,
  parseExplorerQuery,
} from "../lib/explorer";
import { recorded } from "./fixtures/states";
import { neverRunRetired, retiredOf } from "./fixtures/retired";
import { CLOCK, type CheckServer, notFound, ok, renderCheck, setClock, stubServer, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

const emailCheck = recorded.checks.items.find((c) => c.id === "b1ceb8262d8b5441");
if (emailCheck === undefined) throw new Error("fixture missing b1ceb8262d8b5441");

// A distinct id from every active check (it is a different check: one that
// used to be loaded under this id and has since been removed from the files).
const RETIRED_RAN: RetiredCheckSummary = retiredOf(emailCheck, {
  id: "cafef00dcafef00d",
  retired_since: "2026-09-27T08:00:00.000000+00:00",
});
const RETIRED_NEVER_RAN: RetiredCheckSummary = neverRunRetired(
  "deadbeefdeadbeef",
  "orphan_check",
  "sales.customers",
  "lake",
  "2026-09-26T07:00:00.000000+00:00",
);

function explorerChecksBody(retired: RetiredCheckSummary[]): CheckList {
  const items: CheckListItem[] = [...recorded.checks.items, ...retired];
  return { items, total: items.length };
}

async function openExplorer(retired: RetiredCheckSummary[], search = ""): Promise<void> {
  window.history.replaceState(null, "", `/checks${search}`);
  stubServer(recorded, { checks: ok(explorerChecksBody(retired)) });
  render(<App path="/checks" search={search} />);
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

function showing(): string {
  return text(document.querySelector(".explorer__showing") ?? document.body);
}

function retiredToggle(): HTMLInputElement {
  return screen.getByRole<HTMLInputElement>("checkbox", { name: /^Show retired/ });
}

function url(): string {
  return `${window.location.pathname}${window.location.search}`;
}

// ---- lib/explorer.ts: pure functions --------------------------------------

describe("lib/explorer.ts: retired checks (spec 037)", () => {
  it("isRetired narrows on state", () => {
    expect(isRetired(RETIRED_RAN)).toBe(true);
    expect(isRetired(emailCheck)).toBe(false);
  });

  it("matchesRetiredText matches name, dataset, id, datasource, expression, last_known_location, owner and tags, never a null field", () => {
    expect(matchesRetiredText(RETIRED_RAN, "")).toBe(true);
    expect(matchesRetiredText(RETIRED_RAN, "missing_percent")).toBe(true);
    expect(matchesRetiredText(RETIRED_RAN, "sales.customers")).toBe(true);
    expect(matchesRetiredText(RETIRED_RAN, RETIRED_RAN.id)).toBe(true);
    expect(matchesRetiredText(RETIRED_RAN, "tier-1")).toBe(true);
    expect(matchesRetiredText(RETIRED_RAN, "  MISSING_PERCENT  ")).toBe(true);
    expect(matchesRetiredText(RETIRED_RAN, "nowhere")).toBe(false);
    // Null fields (S10, D3) never throw and never match.
    expect(matchesRetiredText(RETIRED_NEVER_RAN, "orphan_check")).toBe(true);
    expect(matchesRetiredText(RETIRED_NEVER_RAN, "nonexistent-expression")).toBe(false);
  });

  it("filterRetired is empty with the toggle off, and filters by the search box with it on", () => {
    expect(filterRetired([RETIRED_RAN, RETIRED_NEVER_RAN], { ...EMPTY_QUERY, retired: false })).toEqual([]);
    expect(filterRetired([RETIRED_RAN, RETIRED_NEVER_RAN], { ...EMPTY_QUERY, retired: true })).toEqual([
      RETIRED_RAN,
      RETIRED_NEVER_RAN,
    ]);
    expect(filterRetired([RETIRED_RAN, RETIRED_NEVER_RAN], { ...EMPTY_QUERY, retired: true, q: "orphan" })).toEqual([
      RETIRED_NEVER_RAN,
    ]);
  });

  it("the URL roundtrips retired=1, last among the parameters, and omits it when off", () => {
    expect(explorerSearch({ ...EMPTY_QUERY, retired: true })).toBe("?retired=1");
    expect(explorerSearch({ ...EMPTY_QUERY, q: "x", statuses: ["fail"], retired: true })).toBe(
      "?q=x&status=fail&retired=1",
    );
    expect(explorerSearch({ ...EMPTY_QUERY, retired: false })).toBe("");
    expect(parseExplorerQuery("?retired=1").retired).toBe(true);
    expect(parseExplorerQuery("?retired=yes").retired).toBe(false);
    expect(parseExplorerQuery("").retired).toBe(false);
  });
});

// ---- S12: the explorer's "Show retired" toggle -----------------------------

describe("S12: the check explorer's 'Show retired' toggle", () => {
  it("is off by default: no retired row, no retired badge, and the header count excludes it", async () => {
    await openExplorer([RETIRED_RAN, RETIRED_NEVER_RAN]);
    expect(screen.queryByText("Retired")).toBeNull();
    expect(document.querySelector(`[data-check-id="${RETIRED_RAN.id}"]`)).toBeNull();
    expect(showing()).toBe(`Showing all ${String(recorded.checks.items.length)} checks.`);
  });

  it("adds retired checks with a Retired badge, alongside Disabled, when switched on", async () => {
    await openExplorer([RETIRED_RAN, RETIRED_NEVER_RAN]);
    fireEvent.click(retiredToggle());
    const row = document.querySelector<HTMLElement>(`[data-check-id="${RETIRED_RAN.id}"]`);
    if (row === null) throw new Error("no row for the retired check");
    expect(within(row).getByText("Retired")).toBeTruthy();
    expect(within(row).getByText("Disabled")).toBeTruthy();
    const neverRan = document.querySelector<HTMLElement>(`[data-check-id="${RETIRED_NEVER_RAN.id}"]`);
    expect(neverRan).not.toBeNull();
    // The header count now includes both retired checks (S12).
    expect(showing()).toBe(`Showing all ${String(recorded.checks.items.length + 2)} checks.`);
  });

  it("keeps the toggle in the URL, remembered across a reload", async () => {
    await openExplorer([RETIRED_RAN], "?retired=1");
    expect(retiredToggle().checked).toBe(true);
    expect(url()).toBe("/checks?retired=1");
    fireEvent.click(retiredToggle());
    expect(url()).toBe("/checks");
    expect(document.querySelector(`[data-check-id="${RETIRED_RAN.id}"]`)).toBeNull();
  });

  it("hides the toggle itself when there is nothing retired", async () => {
    await openExplorer([]);
    expect(screen.queryByRole("checkbox", { name: /^Show retired/ })).toBeNull();
  });

  it("the retired check's row links to its page", async () => {
    await openExplorer([RETIRED_RAN], "?retired=1");
    const row = document.querySelector<HTMLElement>(`[data-check-id="${RETIRED_RAN.id}"]`);
    if (row === null) throw new Error("no row");
    const link = within(row).getByRole("link", { name: RETIRED_RAN.name });
    expect(link.getAttribute("href")).toBe(`/checks/${RETIRED_RAN.id}`);
  });
});

// ---- S13: a retired check's own page --------------------------------------

async function renderRetiredCheck(
  check: RetiredCheckSummary,
  history: CheckServer["history"] = ok({ items: [], next_cursor: null }),
): Promise<void> {
  await renderCheck(check.id, {
    check: ok(check),
    history,
    sql: notFound(),
    source: notFound(),
  });
}

describe("S13: a retired check's page", () => {
  it("shows the Retired badge, 'Retired since …', and the file it was last defined in", async () => {
    await renderRetiredCheck(RETIRED_RAN, ok({ items: [], next_cursor: null }));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toContain(RETIRED_RAN.name);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(within(heading).getByText("Retired")).toBeTruthy();
    expect(screen.getByText(/Retired since/)).toBeTruthy();
    expect(screen.getByText(RETIRED_RAN.last_known_location ?? "", { exact: false })).toBeTruthy();
  });

  it("omits the file when the check was registered but never run (S10)", async () => {
    await renderRetiredCheck(RETIRED_NEVER_RAN);
    expect(screen.getByText(/Retired since/)).toBeTruthy();
    expect(screen.queryByText(/last defined in/)).toBeNull();
  });

  it("shows the latest result and history as for any check, with no SQL or source tabs", async () => {
    const historyPage = ok({
      items: [
        {
          run_id: RETIRED_RAN.latest?.run_id ?? "a0000000000000000000000000000001",
          started_at: RETIRED_RAN.latest?.started_at ?? "2026-09-26T06:56:12.000000+00:00",
          trigger: "cli",
          outcome: RETIRED_RAN.latest?.outcome ?? "fail",
          value: RETIRED_RAN.latest?.value ?? 20,
          display_value: RETIRED_RAN.latest?.display_value ?? "20.00%",
          message: RETIRED_RAN.latest?.message ?? null,
          duration_ms: 3.2,
          name: RETIRED_RAN.name,
          expression: RETIRED_RAN.expression,
          source: RETIRED_RAN.last_known_location,
          metric: RETIRED_RAN.metric,
          dataset: RETIRED_RAN.dataset,
          unit: RETIRED_RAN.unit,
        },
      ],
      next_cursor: null,
    });
    await renderRetiredCheck(RETIRED_RAN, historyPage);
    expect(screen.getByRole("region", { name: "Latest result" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "History" })).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "SQL" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Source" })).toBeNull();
    expect(document.getElementById("sql")).toBeNull();
    expect(document.getElementById("source")).toBeNull();
  });

  it("does not request /sql or /source as a failure: the status line stays clean", async () => {
    await renderRetiredCheck(RETIRED_RAN);
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
