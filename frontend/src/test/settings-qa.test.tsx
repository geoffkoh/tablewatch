/**
 * QA for the Settings page (spec 040): S4/S5 end to end on the page, S-D6
 * tables, S-D7 read-only, S11 Retry recovering.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Settings } from "../api/types";
import { App } from "../App";
import { baseSettings } from "./fixtures/settings";
import { recorded } from "./fixtures/states";
import { CLOCK, ok, setClock, text, UNAVAILABLE, URLS, type Answer } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

async function waitLoaded(): Promise<void> {
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

/** Each URL answers from its queue in turn; the last answer repeats. */
function stub(settings: Answer[]): ReturnType<typeof vi.fn> {
  const queues: Record<string, Answer[]> = {
    [URLS.project]: [ok(recorded.project)],
    [URLS.settings]: settings,
    [URLS.problems]: [ok({ items: [], total: 0 })],
  };
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const queue = queues[url];
    if (queue === undefined) return Promise.reject(new Error(`unexpected request: ${url}`));
    const answer = queue.length > 1 ? queue.shift()! : queue[0]!;
    if (answer === "network-error") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve(
      new Response(JSON.stringify(answer.body), { status: answer.status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function renderWith(settings: Settings): Promise<void> {
  window.history.replaceState(null, "", "/settings");
  stub([ok(settings)]);
  render(<App path="/settings" />);
  await waitLoaded();
}

function section(heading: string): HTMLElement {
  const s = screen.getByRole("heading", { name: heading }).closest("section");
  if (s === null) throw new Error(`no section ${heading}`);
  return s;
}

function bodyRows(el: HTMLElement): string[][] {
  return Array.from(el.querySelectorAll("tbody tr")).map((tr) =>
    Array.from(tr.children).map((c) => (c.textContent ?? "").trim()),
  );
}

describe("S-D6 tables", () => {
  it("lists datasources in config order with type and counts", async () => {
    await renderWith(baseSettings);
    expect(bodyRows(section("Datasources"))).toEqual([
      ["lake", "duckdb", "3", "18"],
      ["lake2", "postgresql", "0", "0"],
    ]);
  });

  it("lists notifiers with the variable as ${env:NAME} in a <code>", async () => {
    await renderWith(baseSettings);
    const notifiers = section("Notifiers");
    expect(bodyRows(notifiers)).toEqual([
      ["ops", "slack", "${env:OPS_SLACK}"],
      ["hook", "webhook", "${env:HOOK_URL}"],
    ]);
    const codes = Array.from(notifiers.querySelectorAll("tbody code")).map((c) => c.textContent);
    expect(codes).toEqual(["${env:OPS_SLACK}", "${env:HOOK_URL}"]);
  });

  it("shows the store's dialect under Database", async () => {
    await renderWith({ ...baseSettings, results: { ...baseSettings.results, dialect: "postgresql" } });
    expect(text(section("Results store"))).toContain("postgresql");
  });

  it("shows Retired 0 as 0, not as —", async () => {
    await renderWith({ ...baseSettings, checks: { active: 3, disabled: 1, retired: 0 } });
    const checks = text(section("Checks"));
    expect(checks).toContain("Active 3");
    expect(checks).toContain("Disabled 1");
    expect(checks).toContain("Retired 0");
    expect(checks).not.toContain("—");
  });

  it("S7: 3 active, 1 disabled, 2 retired", async () => {
    await renderWith({ ...baseSettings, checks: { active: 3, disabled: 1, retired: 2 } });
    const checks = text(section("Checks"));
    expect(checks).toContain("Active 3");
    expect(checks).toContain("Disabled 1");
    expect(checks).toContain("Retired 2");
  });
});

describe("S4 / S5 on the page", () => {
  it("S4: unavailable store reads 'Could not be read', Retired —, and no revision is shown", async () => {
    await renderWith({
      ...baseSettings,
      results: { ...baseSettings.results, schema: "unavailable", revision: null, head: "0009" },
      checks: { active: 12, disabled: 0, retired: null },
    });
    const results = text(section("Results store"));
    expect(results).toContain("Could not be read");
    expect(results).not.toContain("null");
    expect(text(section("Checks"))).toContain("Retired —");
  });

  it("S5: a newer revision id is shown as text", async () => {
    await renderWith({
      ...baseSettings,
      results: { ...baseSettings.results, schema: "newer", revision: "9999_from_the_future", head: "0009" },
      checks: { ...baseSettings.checks, retired: null },
    });
    expect(text(section("Results store"))).toContain("Newer than this tablewatch (9999_from_the_future)");
  });
});

describe("S10: markup in every rendered field", () => {
  it("renders markup in a revision, a type and a checks_path as text", async () => {
    const M = "<svg onload=alert(1)>";
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    await renderWith({
      ...baseSettings,
      project: { ...baseSettings.project, name: M, checks_path: M },
      datasources: [{ name: "ds", type: M, datasets: 0, checks: 0 }],
      notifiers: [{ name: "n", type: "slack", url_variable: M }],
      results: { ...baseSettings.results, schema: "newer", revision: M, dialect: M },
    });
    expect(document.querySelectorAll("main svg[onload], main [onload], main script").length).toBe(0);
    expect(alert).not.toHaveBeenCalled();
    expect(text(section("Results store"))).toContain(M);
  });
});

describe("S-D7: read-only", () => {
  it("has no form control, and no button in the page body", async () => {
    await renderWith(baseSettings);
    const main = screen.getByRole("main");
    expect(main.querySelectorAll("input, select, textarea, form").length).toBe(0);
    expect(within(main).queryAllByRole("button")).toHaveLength(0);
  });
});

describe("S11: Retry recovers", () => {
  it("after a failed load, Try again shows the settings and the nav", async () => {
    window.history.replaceState(null, "", "/settings");
    stub([UNAVAILABLE, ok(baseSettings)]);
    render(<App path="/settings" />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("heading", { name: "Project" })).toBeTruthy();
    });
    expect(screen.queryByRole("alert")).toBeNull();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(nav.querySelector('a[aria-current="page"]')?.getAttribute("href")).toBe("/settings");
  });

  it("a network error also shows LoadError with Retry", async () => {
    window.history.replaceState(null, "", "/settings");
    stub(["network-error"]);
    render(<App path="/settings" />);
    await waitLoaded();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});
