import { render, screen, within, type RenderResult } from "@testing-library/react";
import { vi } from "vitest";
import { App } from "../App";
import { genericSource, SOURCE_BY_ID } from "./fixtures/source";
import { genericSql, SQL_BY_ID } from "./fixtures/sql";
import { interrupted, type OverviewResponses } from "./fixtures/states";

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

// ---- the check page (spec 004) ----------------------------------------------

export interface CheckServer {
  project?: Answer;
  check?: Answer;
  history?: Answer;
  runs?: Answer;
  /**
   * `/checks/{id}/sql`. By default it follows `/checks/{id}`: 404 when the
   * check is not loaded, otherwise the captured body for the id (or a generic
   * one), since `/sql` never reads the store (spec 005, S9).
   */
  sql?: Answer;
  /**
   * `/checks/{id}/source`, by the same rule as `sql` (spec 006): 404 when the
   * check is not loaded, otherwise the captured body for the id or a generic one.
   */
  source?: Answer;
  /** Later history pages, by cursor. */
  older?: Record<string, Answer>;
}

/** The URLs the check page requests for an id. */
export function checkUrls(id: string): {
  project: string;
  check: string;
  history: string;
  runs: string;
  sql: string;
  source: string;
} {
  const enc = encodeURIComponent(id);
  return {
    project: URLS.project,
    check: `/api/v1/checks/${enc}`,
    history: `/api/v1/checks/${enc}/history?limit=200`,
    runs: URLS.runs,
    sql: `/api/v1/checks/${enc}/sql`,
    source: `/api/v1/checks/${enc}/source`,
  };
}

/** The default `/sql` answer for a check answer (see `CheckServer.sql`). */
export function defaultSql(id: string, check: Answer | undefined): Answer {
  if (check === undefined || (check !== "network-error" && check.status === 404)) return notFound();
  const captured = SQL_BY_ID[id];
  if (captured !== undefined) return ok({ ...captured, check_id: id });
  const body: unknown = check === "network-error" ? null : check.body;
  if (typeof body === "object" && body !== null && "dataset" in body && "datasource" in body) {
    const { dataset, datasource } = body;
    if (typeof dataset === "string" && typeof datasource === "string") return ok(genericSql(id, dataset, datasource));
  }
  return ok(genericSql(id));
}

/** The default `/source` answer for a check answer (see `CheckServer.source`). */
export function defaultSource(id: string, check: Answer | undefined): Answer {
  if (check === undefined || (check !== "network-error" && check.status === 404)) return notFound();
  const captured = SOURCE_BY_ID[id];
  return ok(captured === undefined ? genericSource(id) : { ...captured, check_id: id });
}

export function olderUrl(id: string, cursor: string): string {
  return `/api/v1/checks/${encodeURIComponent(id)}/history?limit=200&cursor=${encodeURIComponent(cursor)}`;
}

export function notFound(): Answer {
  return { status: 404, body: { error: { code: "not_found", message: "no such check" } } };
}

export const UNAVAILABLE: Answer = {
  status: 503,
  body: { error: { code: "store_unavailable", message: "results store: unavailable — see the server log" } },
};

/** Replace `fetch` with one that answers the check page's endpoints for an id. */
export function stubCheckServer(id: string, server: CheckServer, base: OverviewResponses = interrupted): ReturnType<typeof vi.fn> {
  const urls = checkUrls(id);
  const answers: Record<string, Answer> = {
    [urls.project]: server.project ?? ok(base.project),
    [urls.check]: server.check ?? notFound(),
    [urls.history]: server.history ?? notFound(),
    [urls.runs]: server.runs ?? ok(base.runs),
    [urls.sql]: server.sql ?? defaultSql(id, server.check),
    [urls.source]: server.source ?? defaultSource(id, server.check),
  };
  for (const [cursor, answer] of Object.entries(server.older ?? {})) answers[olderUrl(id, cursor)] = answer;
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

/** Render `/checks/<id>` and wait until it has loaded. */
export async function renderCheck(id: string, server: CheckServer, path?: string): Promise<RenderResult> {
  stubCheckServer(id, server);
  const result = render(<App path={path ?? `/checks/${encodeURIComponent(id)}`} />);
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
  return result;
}
