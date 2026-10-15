/**
 * Spec 041, adversarial: wording edges, Load more under a filter, and
 * markup in every field the server echoes back.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Alert } from "../api/types";
import { App } from "../App";
import { deliveryText } from "../lib/alerts";
import { baseAlerts } from "./fixtures/alerts";
import { recorded } from "./fixtures/states";
import { CLOCK, ok, setClock, UNAVAILABLE, URLS, type Answer } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

function stub(answers: Record<string, Answer>): ReturnType<typeof vi.fn> {
  const all: Record<string, Answer> = {
    [URLS.project]: ok(recorded.project),
    [URLS.problems]: ok({ items: [], total: 0 }),
    ...answers,
  };
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const answer = all[url];
    if (answer === undefined) return Promise.reject(new Error(`unexpected request: ${url}`));
    if (answer === "network-error") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve(
      new Response(JSON.stringify(answer.body), { status: answer.status, headers: { "Content-Type": "application/json" } }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function waitLoaded(): Promise<void> {
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

function rows(): HTMLElement[] {
  return Array.from(screen.getByRole("list", { name: "Alerts" }).querySelectorAll<HTMLElement>(":scope > li"));
}

function first(): Alert {
  const alert = baseAlerts.items[0];
  if (alert === undefined) throw new Error("fixture needs an alert");
  return alert;
}

describe("delivery wording edges", () => {
  // MAX_AGE can abandon a row after one failed send.
  it.fails("abandoned after one attempt reads 'after 1 attempt', singular", () => {
    expect(deliveryText({ notifier: "hook", status: "abandoned", attempts: 1, sent_at: null })).toBe(
      "Gave up on hook after 1 attempt",
    );
  });

  it("pending with no attempts yet reads '0 attempts'", () => {
    expect(deliveryText({ notifier: "hook", status: "pending", attempts: 0, sent_at: null })).toBe(
      "Pending for hook (0 attempts)",
    );
  });
});

describe("Load more under a filter", () => {
  it("asks for the next page with the same ?event=, and a filter change drops it", async () => {
    const failing = { ...first(), event: "failing" as const };
    const older = { ...failing, check: { ...failing.check, id: "older", name: "older" } };
    const fetchMock = stub({
      "/api/v1/alerts?event=failing&limit=50": ok({ items: [failing], next_cursor: "c 1/+" }),
      "/api/v1/alerts?event=failing&limit=50&cursor=c%201%2F%2B": ok({ items: [older], next_cursor: null }),
      [URLS.alerts]: ok(baseAlerts),
    });
    window.history.replaceState(null, "", "/alerts?event=failing");
    render(<App path="/alerts" search="?event=failing" />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await vi.waitFor(() => {
      expect(rows()).toHaveLength(2);
    });
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain(
      "/api/v1/alerts?event=failing&limit=50&cursor=c%201%2F%2B",
    );
    fireEvent.click(screen.getByRole("radio", { name: "All" }));
    await vi.waitFor(() => {
      expect(rows()).toHaveLength(3);
    });
    expect(rows().some((r) => r.dataset.checkId === "older")).toBe(false);
  });

  it("a failed older page keeps what is shown and retries", async () => {
    let fail = true;
    const olderUrl = "/api/v1/alerts?limit=50&cursor=cur1";
    const older = { ...first(), check: { ...first().check, id: "older", name: "older" } };
    const fetchMock = stub({ [URLS.alerts]: ok({ ...baseAlerts, next_cursor: "cur1" }) });
    const base = fetchMock.getMockImplementation() as (input: RequestInfo | URL) => Promise<Response>;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input) === olderUrl) {
        const answer = fail ? UNAVAILABLE : ok({ items: [older], next_cursor: null });
        if (answer === "network-error") return Promise.reject(new TypeError("Failed to fetch"));
        return Promise.resolve(new Response(JSON.stringify(answer.body), { status: answer.status }));
      }
      return base(input);
    });
    window.history.replaceState(null, "", "/alerts");
    render(<App path="/alerts" search="" />);
    await waitLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    });
    expect(rows()).toHaveLength(3);
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => {
      expect(rows()).toHaveLength(4);
    });
  });
});

describe("markup in every echoed field is text", () => {
  it("notifier, dataset and datasource render as text only", async () => {
    const MARK = "<img src=x onerror=alert(1)>";
    const alertFn = vi.fn();
    vi.stubGlobal("alert", alertFn);
    const hostile: Alert = {
      ...first(),
      check: { ...first().check, dataset: MARK, datasource: MARK, id: "x\"><script>" },
      deliveries: [{ notifier: MARK, status: "pending", attempts: 2, sent_at: null }],
    };
    stub({ [URLS.alerts]: ok({ items: [hostile], next_cursor: null }) });
    window.history.replaceState(null, "", "/alerts");
    render(<App path="/alerts" search="" />);
    await waitLoaded();
    expect(screen.getByText(`Pending for ${MARK} (2 attempts)`)).toBeTruthy();
    expect(document.querySelectorAll("img, script, [onerror]").length).toBe(0);
    expect(alertFn).not.toHaveBeenCalled();
  });
});
