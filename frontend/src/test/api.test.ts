/** The one client: relative same-origin URLs, and every failure explained (O9). */
import { describe, expect, it, vi } from "vitest";
import { ApiError, getProject, listChecks, listRuns } from "../api/api";
import { recorded } from "./fixtures/states";

function answer(status: number, body: string): ReturnType<typeof vi.fn> {
  const mock = vi.fn(() => Promise.resolve(new Response(body, { status })));
  vi.stubGlobal("fetch", mock);
  return mock;
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("expected a failure");
}

describe("api", () => {
  it("requests relative /api/v1 URLs with GET, no cache, same-origin credentials", async () => {
    const mock = answer(200, JSON.stringify(recorded.project));
    await getProject();
    answer(200, JSON.stringify(recorded.checks));
    await listChecks();
    const runs = answer(200, JSON.stringify(recorded.runs));
    await listRuns(1);
    expect(mock.mock.calls[0]?.[0]).toBe("/api/v1/project");
    expect(runs.mock.calls[0]?.[0]).toBe("/api/v1/runs?limit=1");
    const init = mock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.method).toBe("GET");
    expect(init?.cache).toBe("no-store");
    expect(init?.credentials).toBe("same-origin");
  });

  it("returns the body on 200", async () => {
    answer(200, JSON.stringify(recorded.checks));
    expect((await listChecks()).total).toBe(18);
  });

  it("carries the error envelope's code and message", async () => {
    answer(503, JSON.stringify({ error: { code: "store_unavailable", message: "results store: unavailable — see the server log" } }));
    const error = await failure(listChecks());
    expect(error.failure).toEqual({
      kind: "http",
      status: 503,
      code: "store_unavailable",
      message: "results store: unavailable — see the server log",
    });
  });

  it("explains a non-JSON error", async () => {
    answer(502, "<html>Bad gateway</html>");
    const error = await failure(listChecks());
    expect(error.failure).toMatchObject({ kind: "http", status: 502, code: null });
    expect(error.message).toContain("502");
  });

  it("explains a 200 that is not JSON", async () => {
    answer(200, "<html></html>");
    const error = await failure(getProject());
    expect(error.message).toMatch(/not JSON/);
  });

  it("explains a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    const error = await failure(getProject());
    expect(error.failure.kind).toBe("network");
    expect(error.message).toMatch(/could not reach/i);
  });
});
