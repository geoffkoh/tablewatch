/**
 * The Settings page, `/settings` (spec 040, scenarios S9-S11, S13; S-D6's
 * wordings).
 */
import { render, screen, within } from "@testing-library/react";
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

/** Stub the three requests the Settings page makes: `/project`, `/settings` and the nav's badge. */
function stubSettingsServer(
  settings: Answer,
  overrides: { project?: Answer; problems?: Answer } = {},
): ReturnType<typeof vi.fn> {
  const answers: Record<string, Answer> = {
    [URLS.project]: overrides.project ?? ok(recorded.project),
    [URLS.settings]: settings,
    [URLS.problems]: overrides.problems ?? ok({ items: [], total: 0 }),
  };
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const answer = answers[url];
    if (answer === undefined) return Promise.reject(new Error(`unexpected request: ${url}`));
    if (answer === "network-error") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve(
      new Response(JSON.stringify(answer.body), { status: answer.status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderSettingsPage(settings: Settings, overrides: { project?: Answer; problems?: Answer } = {}): ReturnType<typeof vi.fn> {
  window.history.replaceState(null, "", "/settings");
  const fetchMock = stubSettingsServer(ok(settings), overrides);
  render(<App path="/settings" />);
  return fetchMock;
}

function sectionFor(heading: string): HTMLElement {
  const h = screen.getByRole("heading", { name: heading });
  const section = h.closest("section");
  if (section === null) throw new Error(`no section for "${heading}"`);
  return section;
}

describe("S9: the nav on the Settings page", () => {
  it("lists Dashboard, Checks, Datasets, Settings in order, and marks Settings current", async () => {
    renderSettingsPage(baseSettings);
    await waitLoaded();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const hrefs = within(nav)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/checks", "/datasets", "/settings"]);
    const current = nav.querySelectorAll('a[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe("/settings");
  });
});

describe("S10: a hostile datasource or notifier name", () => {
  it("renders as text", async () => {
    const NAME = "<img src=x onerror=alert(1)>";
    const settings: Settings = {
      ...baseSettings,
      datasources: [{ name: NAME, type: "duckdb", datasets: 1, checks: 1 }],
      notifiers: [{ name: NAME, type: "slack", url_variable: "OPS_SLACK" }],
    };
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    renderSettingsPage(settings);
    await waitLoaded();
    expect(screen.getAllByText(NAME, { exact: false }).length).toBeGreaterThan(0);
    expect(document.querySelectorAll("img, script, [onerror]").length).toBe(0);
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("S11: /settings fails to load", () => {
  it("shows the shared LoadError with Retry, and the nav still renders", async () => {
    window.history.replaceState(null, "", "/settings");
    stubSettingsServer(UNAVAILABLE);
    render(<App path="/settings" />);
    await waitLoaded();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Project" })).toBeNull();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(within(nav).getAllByRole("link")).toHaveLength(4);
  });
});

describe("S13: no datasources or notifiers configured", () => {
  it("reads 'No datasources.' and 'No notifiers configured.'", async () => {
    const settings: Settings = { ...baseSettings, datasources: [], notifiers: [] };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(screen.getByText("No datasources.")).toBeTruthy();
    expect(screen.getByText("No notifiers configured.")).toBeTruthy();
  });
});

describe("S-D6: the Project section", () => {
  it("shows the name, tablewatch version and loaded age", async () => {
    renderSettingsPage(baseSettings);
    await waitLoaded();
    const section = sectionFor("Project");
    expect(text(section)).toContain("retail-example");
    expect(text(section)).toContain("0.1.0");
    expect(text(section)).toContain("checks");
  });

  it("reads 'Outside the project' when checks_path is null", async () => {
    const settings: Settings = { ...baseSettings, project: { ...baseSettings.project, checks_path: null } };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Project"))).toContain("Outside the project");
  });
});

describe("S-D6: the store's schema in words", () => {
  it("current reads 'Up to date (<revision>)'", async () => {
    const settings: Settings = {
      ...baseSettings,
      results: { ...baseSettings.results, schema: "current", revision: "rev1", head: "rev1" },
    };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Up to date (rev1)");
  });

  it("older reads 'Older than this tablewatch (<revision>; this version is at <head>)'", async () => {
    const settings: Settings = {
      ...baseSettings,
      results: { ...baseSettings.results, schema: "older", revision: "rev1", head: "rev2" },
    };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Older than this tablewatch (rev1; this version is at rev2)");
  });

  it("newer reads 'Newer than this tablewatch (<revision>)'", async () => {
    const settings: Settings = {
      ...baseSettings,
      results: { ...baseSettings.results, schema: "newer", revision: "rev3", head: "rev2" },
    };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Newer than this tablewatch (rev3)");
  });

  it("empty reads 'Nothing recorded yet', and Retired reads '—'", async () => {
    const settings: Settings = {
      ...baseSettings,
      results: { ...baseSettings.results, schema: "empty", revision: null },
      checks: { ...baseSettings.checks, retired: null },
    };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Nothing recorded yet");
    expect(text(sectionFor("Checks"))).toContain("Retired —");
  });

  it("unavailable reads 'Could not be read', and Retired reads '—'", async () => {
    const settings: Settings = {
      ...baseSettings,
      results: { ...baseSettings.results, schema: "unavailable", revision: null },
      checks: { ...baseSettings.checks, retired: null },
    };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Could not be read");
    expect(text(sectionFor("Checks"))).toContain("Retired —");
  });
});

describe("S-D6: Migrations and Registry sync in words", () => {
  it("migrate: auto reads 'Applied by tablewatch when a run opens the store'", async () => {
    const settings: Settings = { ...baseSettings, results: { ...baseSettings.results, migrate: "auto" } };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Applied by tablewatch when a run opens the store");
  });

  it("migrate: never reads 'Managed outside tablewatch (tablewatch store sql)'", async () => {
    const settings: Settings = { ...baseSettings, results: { ...baseSettings.results, migrate: "never" } };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Managed outside tablewatch (tablewatch store sql)");
  });

  it("sync: on_run reads 'On every recorded run'", async () => {
    const settings: Settings = { ...baseSettings, results: { ...baseSettings.results, sync: "on_run" } };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("On every recorded run");
  });

  it("sync: manual reads 'Only by tablewatch sync'", async () => {
    const settings: Settings = { ...baseSettings, results: { ...baseSettings.results, sync: "manual" } };
    renderSettingsPage(settings);
    await waitLoaded();
    expect(text(sectionFor("Results store"))).toContain("Only by tablewatch sync");
  });
});

describe("the page's own requests and title", () => {
  it("requests /project, /settings and the nav badge, and titles the page", async () => {
    const fetchMock = renderSettingsPage(baseSettings);
    await waitLoaded();
    const urls = fetchMock.mock.calls.map((c) => String(c[0])).sort();
    expect(urls).toEqual([URLS.project, URLS.settings, URLS.problems].sort());
    await vi.waitFor(() => {
      expect(document.title).toBe("Settings — retail-example");
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Settings");
  });
});
