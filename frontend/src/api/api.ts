/**
 * The one client for `/api/v1`. Components never call `fetch` themselves.
 *
 * Every URL is relative and same-origin (spec 003, X3): the bundle is served
 * by `tablewatch serve` next to the API, and the CSP allows `connect-src
 * 'self'` only.
 */
import type { CheckList, ErrorBody, ErrorCode, Project, RunPage } from "./types";

const BASE = "/api/v1";

/** Why a request did not produce data. */
export type ApiFailure =
  | { kind: "http"; status: number; code: ErrorCode | null; message: string }
  | { kind: "network"; message: string };

/** Thrown by every client function; carries what the page shows. */
export class ApiError extends Error {
  readonly failure: ApiFailure;

  constructor(failure: ApiFailure) {
    super(failure.message);
    this.name = "ApiError";
    this.failure = failure;
  }
}

function isErrorBody(body: unknown): body is ErrorBody {
  if (typeof body !== "object" || body === null || !("error" in body)) return false;
  const error: unknown = body.error;
  return (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string" &&
    "code" in error &&
    typeof error.code === "string"
  );
}

async function get<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError({
      kind: "network",
      message: "Could not reach the tablewatch server. Is `tablewatch serve` still running?",
    });
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    if (isErrorBody(body)) {
      throw new ApiError({
        kind: "http",
        status: response.status,
        code: body.error.code,
        message: body.error.message,
      });
    }
    throw new ApiError({
      kind: "http",
      status: response.status,
      code: null,
      message: `The server answered ${String(response.status)} without an explanation.`,
    });
  }
  if (body === null) {
    throw new ApiError({
      kind: "http",
      status: response.status,
      code: null,
      message: "The server's answer was not JSON.",
    });
  }
  // The body's shape is the contract's; the types are generated from it.
  return body as T;
}

/** `GET /api/v1/project`: the project as loaded at startup. */
export function getProject(): Promise<Project> {
  return get<Project>("/project");
}

/** `GET /api/v1/checks`: every loaded check with its latest result. */
export function listChecks(): Promise<CheckList> {
  return get<CheckList>("/checks");
}

/** `GET /api/v1/runs?limit=N`: runs, newest first. */
export function listRuns(limit: number): Promise<RunPage> {
  return get<RunPage>(`/runs?limit=${encodeURIComponent(String(limit))}`);
}
