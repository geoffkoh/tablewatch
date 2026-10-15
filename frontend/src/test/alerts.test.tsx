/**
 * The Alerts page, `/alerts` (spec 041, scenarios A8-A15).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Alert, AlertPage } from "../api/types";
import { App } from "../App";
import { baseAlerts } from "./fixtures/alerts";
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

interface AlertsServer {
  project?: Answer;
  alerts?: Answer;
  problems?: Answer;
  /** Later pages, by their exact request URL (query string and all). */
  more?: Record<string, Answer>;
}

function stubAlertsServer(server: AlertsServer): ReturnType<typeof vi.fn> {
  const answers: Record<string, Answer> = {
    [URLS.project]: server.project ?? ok(recorded.project),
    [URLS.alerts]: server.alerts ?? ok({ items: [], next_cursor: null }),
    [URLS.problems]: server.problems ?? ok({ items: [], total: 0 }),
    ...server.more,
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

function renderAlerts(server: AlertsServer, search = ""): ReturnType<typeof vi.fn> {
  window.history.replaceState(null, "", `/alerts${search}`);
  const fetchMock = stubAlertsServer(server);
  render(<App path="/alerts" search={search} />);
  return fetchMock;
}

function rows(): HTMLElement[] {
  // `:scope > li`: the alert rows only, not the nested per-notifier `<ul>`
  // each row carries for its deliveries.
  return Array.from(screen.getByRole("list", { name: "Alerts" }).querySelectorAll<HTMLElement>(":scope > li"));
}

function rowFor(checkId: string): HTMLElement {
  const row = rows().find((r) => r.dataset.checkId === checkId);
  if (row === undefined) throw new Error(`no row for ${checkId}`);
  return row;
}

describe("the page's own requests, title and nav", () => {
  it("requests /alerts, /project and the nav badge with no filter, and titles the page", async () => {
    const fetchMock = renderAlerts({ alerts: ok(baseAlerts) });
    await waitLoaded();
    const urls = fetchMock.mock.calls.map((c) => String(c[0])).sort();
    expect(urls).toEqual([URLS.alerts, URLS.project, URLS.problems].sort());
    await vi.waitFor(() => {
      expect(document.title).toBe("Alerts — retail-example");
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Alerts");
  });
});

describe("A14: nav", () => {
  it("lists Dashboard, Checks, Datasets, Alerts, Settings, and marks Alerts current", async () => {
    renderAlerts({ alerts: ok(baseAlerts) });
    await waitLoaded();
    const nav = screen.getByRole("navigation", { name: "Sections" });
    const hrefs = within(nav)
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/checks", "/datasets", "/alerts", "/settings"]);
    const current = nav.querySelectorAll('a[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe("/alerts");
  });
});

describe("A13: /alerts fails or is empty", () => {
  it("a failing /alerts shows the shared LoadError with Retry", async () => {
    renderAlerts({ alerts: UNAVAILABLE });
    await waitLoaded();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Alerts" })).toBeNull();
  });

  it("no events recorded reads 'No state changes recorded yet.'", async () => {
    renderAlerts({ alerts: ok({ items: [], next_cursor: null }) });
    await waitLoaded();
    expect(screen.getByText("No state changes recorded yet.")).toBeTruthy();
  });
});

describe("A9: an unkeyed run's deliveries", () => {
  it("reads 'Not recorded (run had no --run-key)'", async () => {
    renderAlerts({ alerts: ok(baseAlerts) });
    await waitLoaded();
    const row = rowFor("inventory-products-completeness");
    expect(text(row)).toContain("Not recorded (run had no --run-key)");
  });
});

describe("A8/A8a: deliveries", () => {
  function pageOf(alert: Alert): AlertPage {
    return { items: [alert], next_cursor: null };
  }

  it("sent and abandoned (MAX_ATTEMPTS, A8) reads 'Sent to ops' and 'Gave up on hook after 5 attempts'", async () => {
    const alert = baseAlerts.items[0];
    if (alert === undefined) throw new Error("fixture needs an alert");
    renderAlerts({
      alerts: ok(
        pageOf({
          ...alert,
          deliveries: [
            { notifier: "ops", status: "sent", attempts: 1, sent_at: "2026-09-26T06:56:50.000000+00:00" },
            { notifier: "hook", status: "abandoned", attempts: 5, sent_at: null },
          ],
        }),
      ),
    });
    await waitLoaded();
    const row = rowFor(alert.check.id);
    expect(text(row)).toContain("Sent to ops");
    expect(text(row)).toContain("Gave up on hook after 5 attempts");
  });

  it("abandoned by MAX_AGE with 0 attempts (A8a) reads 'Gave up on hook (no attempts sent)'", async () => {
    const alert = baseAlerts.items[0];
    if (alert === undefined) throw new Error("fixture needs an alert");
    renderAlerts({
      alerts: ok(pageOf({ ...alert, deliveries: [{ notifier: "hook", status: "abandoned", attempts: 0, sent_at: null }] })),
    });
    await waitLoaded();
    expect(text(rowFor(alert.check.id))).toContain("Gave up on hook (no attempts sent)");
  });

  it("[] reads 'No notification recorded'", async () => {
    const alert = baseAlerts.items[2];
    if (alert === undefined) throw new Error("fixture needs an alert");
    renderAlerts({ alerts: ok(pageOf({ ...alert, deliveries: [] })) });
    await waitLoaded();
    expect(text(rowFor(alert.check.id))).toContain("No notification recorded");
  });
});

describe("A15: a notifier later removed from tablewatch.yml", () => {
  it("still reads its recorded name, unchanged", async () => {
    const alert = baseAlerts.items[0];
    if (alert === undefined) throw new Error("fixture needs an alert");
    renderAlerts({
      alerts: ok({
        items: [{ ...alert, deliveries: [{ notifier: "a-notifier-nobody-configures-any-more", status: "sent", attempts: 1, sent_at: null }] }],
        next_cursor: null,
      }),
    });
    await waitLoaded();
    expect(text(rowFor(alert.check.id))).toContain("Sent to a-notifier-nobody-configures-any-more");
  });
});

describe("A10: a retired check's alert", () => {
  it("is listed, shows Retired, and links to its page", async () => {
    const alert = baseAlerts.items[0];
    if (alert === undefined) throw new Error("fixture needs an alert");
    renderAlerts({
      alerts: ok({ items: [{ ...alert, check: { ...alert.check, state: "retired" } }], next_cursor: null }),
    });
    await waitLoaded();
    const row = rowFor(alert.check.id);
    expect(within(row).getByText("Retired")).toBeTruthy();
    const link = within(row).getByRole("link", { name: alert.check.name });
    expect(link.getAttribute("href")).toBe(`/checks/${alert.check.id}`);
  });
});

describe("wording: event and 'was <previous>'", () => {
  it("failing/erroring/recovered and their previous outcome in words", async () => {
    renderAlerts({ alerts: ok(baseAlerts) });
    await waitLoaded();
    const [recoveredItem, erroringItem, failingItem] = baseAlerts.items;
    if (recoveredItem === undefined || erroringItem === undefined || failingItem === undefined) {
      throw new Error("fixture needs three alerts");
    }
    expect(text(rowFor(recoveredItem.check.id))).toContain("Recovered");
    expect(text(rowFor(recoveredItem.check.id))).toContain("was failing");
    expect(text(rowFor(erroringItem.check.id))).toContain("Started erroring");
    expect(text(rowFor(erroringItem.check.id))).toContain("was failing");
    expect(text(rowFor(failingItem.check.id))).toContain("Started failing");
    expect(text(rowFor(failingItem.check.id))).toContain("was passing");
  });

  it("a null previous_outcome omits 'was' entirely", async () => {
    const alert = baseAlerts.items[2];
    if (alert === undefined) throw new Error("fixture needs an alert");
    renderAlerts({ alerts: ok({ items: [{ ...alert, previous_outcome: null }], next_cursor: null }) });
    await waitLoaded();
    expect(text(rowFor(alert.check.id))).not.toContain("was");
  });
});

describe("A12: filter, Load more, and a hostile check name", () => {
  it("?event=failing is kept, and selecting it reloads /alerts with the parameter", async () => {
    const fetchMock = renderAlerts(
      {
        alerts: ok(baseAlerts),
        more: { "/api/v1/alerts?event=failing&limit=50": ok({ items: [baseAlerts.items[2]], next_cursor: null }) },
      },
      "?event=failing",
    );
    await waitLoaded();
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain("/api/v1/alerts?event=failing&limit=50");
    expect((screen.getByRole("radio", { name: "Failing" }) as HTMLInputElement).checked).toBe(true);

    fetchMock.mockClear();
    const answers: Record<string, Answer> = {
      [URLS.project]: ok(recorded.project),
      [URLS.problems]: ok({ items: [], total: 0 }),
      "/api/v1/alerts?limit=50": ok(baseAlerts),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        const answer = answers[url];
        if (answer === undefined) return Promise.reject(new Error(`unexpected request: ${url}`));
        return Promise.resolve(new Response(JSON.stringify((answer as { body: unknown }).body), { status: 200 }));
      }),
    );
    fireEvent.click(screen.getByRole("radio", { name: "All" }));
    await vi.waitFor(() => {
      expect(window.location.search).toBe("");
    });
    await vi.waitFor(() => {
      expect(rows().length).toBe(3);
    });
  });

  it("'Load more' appends the next page and keeps the cursor out of the URL", async () => {
    const olderUrl = "/api/v1/alerts?limit=50&cursor=cur1";
    renderAlerts({
      alerts: ok({ ...baseAlerts, next_cursor: "cur1" }),
      more: {
        [olderUrl]: ok({
          items: [
            {
              ...baseAlerts.items[0],
              check: { ...baseAlerts.items[0]!.check, id: "older-check", name: "older check" },
            },
          ],
          next_cursor: null,
        }),
      },
    });
    await waitLoaded();
    expect(rows()).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await vi.waitFor(() => {
      expect(rows()).toHaveLength(4);
    });
    expect(rowFor("older-check")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(window.location.search).not.toContain("cursor");
  });

  it("markup in a check name renders as text only", async () => {
    const alert = baseAlerts.items[0];
    if (alert === undefined) throw new Error("fixture needs an alert");
    const NAME = "<img src=x onerror=alert(1)>";
    const alertFn = vi.fn();
    vi.stubGlobal("alert", alertFn);
    renderAlerts({ alerts: ok({ items: [{ ...alert, check: { ...alert.check, name: NAME } }], next_cursor: null }) });
    await waitLoaded();
    expect(screen.getAllByText(NAME, { exact: false }).length).toBeGreaterThan(0);
    expect(document.querySelectorAll("img, script, [onerror]").length).toBe(0);
    expect(alertFn).not.toHaveBeenCalled();
  });
});
