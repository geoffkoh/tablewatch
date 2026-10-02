/**
 * QA, spec 017 P2 and P3 at the edges. `sincePoint` decides the day in the
 * viewer's zone, so each zone case re-imports `lib/time` under its own `TZ`
 * (the formatters bind the zone when the module loads). The suite's default
 * zone is Asia/Singapore (`vite.config.ts`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CheckSummary, Run } from "../api/types";
import { notLoadedFromRun } from "../lib/status";
import { recorded } from "./fixtures/states";
import { renderOverview, setClock } from "./render";

type SincePoint = (iso: string, nowMs: number) => string;

async function sinceIn(zone: string): Promise<SincePoint> {
  vi.stubEnv("TZ", zone);
  vi.resetModules();
  const mod = await import("../lib/time");
  return mod.sincePoint;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
  vi.useRealTimers();
});

const at = (iso: string): number => Date.parse(iso);

describe("P2 in Asia/Singapore: midnight, the year boundary, the future, bad input", () => {
  it("one second before local midnight is yesterday; midnight itself is today", async () => {
    const since = await sinceIn("Asia/Singapore");
    const now = at("2026-09-26T16:00:30Z"); // 00:00:30 Sep 27 SGT
    expect(since("2026-09-26T15:59:59Z", now)).toBe("Sep 26");
    expect(since("2026-09-26T16:00:00Z", now)).toBe("00:00 today");
  });

  it("ten minutes into the new year, last night carries its year", async () => {
    const since = await sinceIn("Asia/Singapore");
    const now = at("2025-12-31T16:10:00Z"); // 00:10 Jan 1 2026 SGT
    expect(since("2025-12-31T15:50:00Z", now)).toBe("Dec 31, 2025");
    expect(since("2025-12-31T16:00:00Z", now)).toBe("00:00 today");
  });

  it("a since far in the future reads as its date with its year, never negative", async () => {
    const since = await sinceIn("Asia/Singapore");
    const now = at("2026-09-26T12:00:00Z");
    expect(since("2099-01-01T00:00:00Z", now)).toBe("Jan 1, 2099");
    expect(since("2026-12-31T00:00:00Z", now)).toBe("Dec 31");
  });

  it.each(["", "garbage", "null", "NaN"])(
    "%j reads 'an unknown time'",
    async (bad) => {
      const since = await sinceIn("Asia/Singapore");
      expect(since(bad, at("2026-09-26T12:00:00Z"))).toBe("an unknown time");
    },
  );

  it("an API timestamp with microseconds and an offset parses", async () => {
    const since = await sinceIn("Asia/Singapore");
    expect(
      since("2026-09-26T02:05:00.123456+00:00", at("2026-09-26T12:00:00Z")),
    ).toBe("10:05 today");
  });
});

describe("P2 under other zones: the viewer's zone decides, not UTC and not Singapore", () => {
  it("America/New_York, the autumn DST day: 00:30 EDT is today at 12:00 EST", async () => {
    const since = await sinceIn("America/New_York");
    const now = at("2026-11-01T17:00:00Z"); // 12:00 EST, Nov 1 (clocks went back at 02:00 EDT)
    expect(since("2026-11-01T04:30:00Z", now)).toBe("00:30 today");
    expect(since("2026-11-01T03:59:00Z", now)).toBe("Oct 31");
  });

  it("America/New_York, the spring DST day: 01:59 EST and 03:00 EDT are both today", async () => {
    const since = await sinceIn("America/New_York");
    const now = at("2026-03-08T16:00:00Z"); // 12:00 EDT, Mar 8
    expect(since("2026-03-08T06:59:00Z", now)).toBe("01:59 today");
    expect(since("2026-03-08T07:00:00Z", now)).toBe("03:00 today");
    expect(since("2026-03-08T04:59:00Z", now)).toBe("Mar 7");
  });

  it("America/New_York: a UTC new year is still last year locally", async () => {
    const since = await sinceIn("America/New_York");
    const now = at("2026-01-01T03:00:00Z"); // 22:00 Dec 31 2025 EST
    expect(since("2026-01-01T02:00:00Z", now)).toBe("21:00 today");
    expect(since("2025-12-30T12:00:00Z", now)).toBe("Dec 30");
  });

  it("Pacific/Kiritimati (UTC+14) and Pacific/Pago_Pago (UTC−11) disagree on the day", async () => {
    const now = at("2026-09-26T12:00:00Z");
    // now is 02:00 Sep 27 at +14 and 01:00 Sep 26 at −11.
    expect(
      (await sinceIn("Pacific/Kiritimati"))("2026-09-26T11:00:00Z", now),
    ).toBe("01:00 today");
    expect(
      (await sinceIn("Pacific/Pago_Pago"))("2026-09-26T11:00:00Z", now),
    ).toBe("00:00 today");
    expect(
      (await sinceIn("Pacific/Kiritimati"))("2026-09-26T09:00:00Z", now),
    ).toBe("Sep 26");
    expect(
      (await sinceIn("Pacific/Pago_Pago"))("2026-09-26T09:00:00Z", now),
    ).toBe("Sep 25");
  });
});

function run(id: string, total: number): Run {
  const base = recorded.runs.items[0];
  if (base === undefined) throw new Error("fixture has no run");
  return { ...structuredClone(base), id, counts: { ...base.counts, total } };
}

function checksFrom(runIds: readonly (string | null)[]): CheckSummary[] {
  const template = recorded.checks.items.find((c) => c.latest !== null);
  if (template?.latest == null) throw new Error("fixture has no result");
  const latest = template.latest;
  return runIds.map((runId, i) => ({
    ...structuredClone(template),
    id: `check${String(i)}`,
    latest: runId === null ? null : { ...latest, run_id: runId },
  }));
}

describe("P3: k = counts.total − loaded checks whose latest is from that run", () => {
  it("a run no loaded check belongs to counts every one of its checks", () => {
    expect(
      notLoadedFromRun(run("R", 5), checksFrom(["OLD", "OLD", null])),
    ).toBe(5);
  });

  it("checks with no result and checks from older runs do not reduce k", () => {
    expect(
      notLoadedFromRun(run("R", 4), checksFrom(["R", "R", null, "OLD"])),
    ).toBe(2);
  });

  it("counts.total 0 gives 0", () => {
    expect(notLoadedFromRun(run("R", 0), checksFrom(["OLD"]))).toBe(0);
  });

  it("no checks loaded gives the whole run", () => {
    expect(notLoadedFromRun(run("R", 3), [])).toBe(3);
  });

  it("a run of 0 checks on the overview says nothing", async () => {
    setClock("2026-09-26T12:00:00Z");
    const state = structuredClone(recorded);
    const latest = state.runs.items[0];
    if (latest === undefined) throw new Error("fixture has no run");
    latest.counts = {
      total: 0,
      pass: 0,
      warn: 0,
      fail: 0,
      error: 0,
      skipped: 0,
    };
    await renderOverview(state);
    expect(document.body.textContent).not.toMatch(
      /not loaded now|NaN|-\d+ of them/,
    );
  });

  it("a counts.total missing from the response says nothing and renders no NaN", async () => {
    setClock("2026-09-26T12:00:00Z");
    const state = structuredClone(recorded);
    const latest = state.runs.items[0];
    if (latest === undefined) throw new Error("fixture has no run");
    delete (latest.counts as Partial<Run["counts"]>).total;
    await renderOverview(state);
    expect(document.body.textContent).not.toMatch(
      /not loaded now|-\d+ of them/,
    );
  });
});
