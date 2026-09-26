import { render, screen, within, type RenderResult } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../App";
import type { OverviewResponses } from "./fixtures/states";

export type Answer = { status: number; body: unknown } | "network-error";

export interface Server {
  project?: Answer;
  checks?: Answer;
  runs?: Answer;
}

/** The URLs the overview is expected to request, and nothing else. */
export const URLS = {
  project: "/api/v1/project",
  checks: "/api/v1/checks",
  runs: "/api/v1/runs?limit=1",
} as const;

export function ok(body: unknown): Answer {
  return { status: 200, body };
}

/** Replace `fetch` with one that answers the three overview endpoints. */
export function stubServer(fixture: OverviewResponses, overrides: Server = {}): ReturnType<typeof vi.fn> {
  const answers: Record<string, Answer> = {
    [URLS.project]: overrides.project ?? ok(fixture.project),
    [URLS.checks]: overrides.checks ?? ok(fixture.checks),
    [URLS.runs]: overrides.runs ?? ok(fixture.runs),
  };
  const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const answer = answers[url];
    if (answer === undefined) return Promise.reject(new Error(`unexpected request: ${url}`));
    if (answer === "network-error") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve(
      new Response(JSON.stringify(answer.body), {
        status: answer.status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Freeze `Date` only; promises and timers stay real. */
export function setClock(iso: string): void {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(iso));
}

/** Run B's started_at plus 3 hours and 43 seconds: every fixture age is "3 hours ago". */
export const CLOCK = "2026-09-26T09:56:55Z";

/** Render the overview for a fixture and wait until it has loaded. */
export async function renderOverview(fixture: OverviewResponses, overrides: Server = {}): Promise<RenderResult> {
  stubServer(fixture, overrides);
  const result = render(<App path="/" />);
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
  return result;
}

/** The check table's body rows, in display order. */
export function rows(): HTMLElement[] {
  const table = screen.getByRole("table");
  const [, body] = within(table).getAllByRole("rowgroup");
  if (body === undefined) throw new Error("no table body");
  return within(body).getAllByRole("row");
}

export function rowFor(id: string): HTMLElement {
  const row = rows().find((r) => r.dataset.checkId === id);
  if (row === undefined) throw new Error(`no row for ${id}`);
  return row;
}

export function statuses(): string[] {
  return rows().map((r) => r.dataset.status ?? "?");
}

/** The summary tile for a status. */
export function tile(status: string): HTMLElement {
  const summary = screen.getByRole("region", { name: "Summary" });
  const found = summary.querySelector<HTMLElement>(`[data-status="${status}"]`);
  if (found === null) throw new Error(`no ${status} tile`);
  return found;
}

/** Collapse whitespace in an element's text. */
export function text(el: Element): string {
  return (el.textContent ?? "").replace(/\s+/g, " ").trim();
}
