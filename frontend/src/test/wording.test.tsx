/**
 * Spec 017: overview wording and counts (I-21), scenario by scenario. The
 * caption alone carries "incomplete" (P1), "since" is a point in time (P2),
 * and the checks the latest run counted that are not loaded now are counted
 * exactly (P3). Vitest runs in Asia/Singapore; now is 20:00 SGT.
 */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LatestResult } from "../api/types";
import { mapLatest, noRunsState } from "./fixtures/derived";
import { detailOf, emailHistory, emailHistoryBeforeF } from "./fixtures/detail";
import { beforeF, interrupted, recorded, RUN_ID, type OverviewResponses } from "./fixtures/states";
import { ok, renderCheck, renderOverview, rowFor, setClock, text } from "./render";

const NOW = "2026-09-26T12:00:00Z";
const FAIL_ID = "fc9cc3088acaf77a";
const WARN_ID = "41e58afff9c48a46";
const SKIP_ID = "cd3e8103b4318809";
const EMAIL = "b1ceb8262d8b5441";

const S1_SINCE = "2026-09-19T03:00:00Z";
const S2_SINCE = "2026-09-26T02:05:00Z";

beforeEach(() => {
  setClock(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

function setLatest(
  state: OverviewResponses,
  id: string,
  change: (latest: LatestResult) => LatestResult,
): OverviewResponses {
  return mapLatest(state, (c) => (c.id === id && c.latest !== null ? change(c.latest) : c.latest));
}

function since(id: string): HTMLElement {
  const el = rowFor(id).querySelector<HTMLElement>(".since");
  if (el === null) throw new Error(`no since on ${id}`);
  return el;
}

interface RunShape {
  ok: boolean;
  /** `counts.total` of the latest run. */
  total: number;
  /** How many of recorded's checks are loaded. */
  loaded: number;
  /** How many of the loaded checks have their latest result from the latest run. */
  inRun: number;
}

/** recorded, cut to `loaded` checks, with `inRun` of them from the latest run. */
function runState({ ok: projectOk, total, loaded, inRun }: RunShape): OverviewResponses {
  const next = structuredClone(recorded);
  const run = next.runs.items[0];
  if (run === undefined) throw new Error("fixture has no run");
  run.counts.total = total;
  const items = next.checks.items.slice(0, loaded).map((c, i) => {
    if (c.latest === null) throw new Error("recorded has a check with no result");
    return { ...c, latest: { ...c.latest, run_id: i < inRun ? run.id : RUN_ID.A } };
  });
  next.checks = { items, total: items.length };
  next.project.counts.checks = items.length;
  next.project.ok = projectOk;
  next.project.diagnostics = projectOk
    ? []
    : [
        {
          severity: "error",
          message: "expected a number, found '<'",
          location: { file: "checks/sales/orders.yml", line: 11, column: 30 },
        },
      ];
  return next;
}

const banner = (): HTMLElement => screen.getByRole("region", { name: "A check file has errors" });
const panel = (): HTMLElement => screen.getByRole("region", { name: "Latest run" });
const summary = (): HTMLElement => screen.getByRole("region", { name: "Summary" });

describe("C: the caption alone carries 'incomplete' (P1)", () => {
  /** 15 checks, one skipped so every tile shows, and a broken file. */
  const broken = (): OverviewResponses => {
    const state = runState({ ok: false, total: 14, loaded: 15, inRun: 15 });
    return setLatest(state, SKIP_ID, (l) => ({ ...l, outcome: "skipped" }));
  };

  it("C1: the caption reads '(incomplete)' and links to the banner", async () => {
    await renderOverview(broken());
    const caption = summary().querySelector(".caption");
    expect(text(caption ?? summary())).toBe("Latest result of each of the 15 checks loaded (incomplete)");
    const marker = within(summary()).getByRole("link", { name: "incomplete" });
    expect(marker.getAttribute("href")).toBe("#project-problems");
    expect(banner().id).toBe("project-problems");
  });

  it("C2: no tile contains the word 'incomplete'", async () => {
    await renderOverview(broken());
    const tiles = Array.from(summary().querySelectorAll(".tile"));
    expect(tiles.map((t) => t.getAttribute("data-status"))).toEqual(["fail", "error", "warn", "none", "skipped", "pass"]);
    for (const t of tiles) expect(t.textContent).not.toMatch(/incomplete/i);
    expect(within(summary()).getAllByRole("link", { name: "incomplete" })).toHaveLength(1);
  });

  it("C3: with ok true, 'incomplete' appears nowhere", async () => {
    await renderOverview(recorded);
    expect(document.body.textContent).not.toMatch(/incomplete/i);
  });
});

describe("S: 'since' is a point in time (P2)", () => {
  it("S1: an earlier day this year reads 'Failing since Sep 19', with the API string and the full time", async () => {
    await renderOverview(setLatest(recorded, FAIL_ID, (l) => ({ ...l, since: S1_SINCE })));
    expect(text(since(FAIL_ID))).toBe("Failing since Sep 19");
    const time = since(FAIL_ID).querySelector("time");
    expect(time?.getAttribute("dateTime")).toBe(S1_SINCE);
    expect(time?.getAttribute("title")).toMatch(/^Sep 19, 2026, 11:00:00 (GMT\+8|SGT)$/);
    expect(time?.getAttribute("data-full")).toBe(time?.getAttribute("title"));
    expect(time?.tabIndex).toBe(0);
  });

  it("S2: the same local day reads the time and 'today'", async () => {
    await renderOverview(setLatest(recorded, FAIL_ID, (l) => ({ ...l, since: S2_SINCE })));
    expect(text(since(FAIL_ID))).toBe("Failing since 10:05 today");
  });

  it("S3: the viewer's zone decides the day and the year", async () => {
    await renderOverview(setLatest(recorded, WARN_ID, (l) => ({ ...l, since: "2025-12-31T20:00:00Z" })));
    expect(text(since(WARN_ID))).toBe("Warning since Jan 1");
  });

  it("S4: another year adds the year", async () => {
    await renderOverview(
      setLatest(recorded, SKIP_ID, (l) => ({ ...l, outcome: "skipped", since: "2025-12-31T15:00:00Z" })),
    );
    expect(text(since(SKIP_ID))).toBe("Skipped since Dec 31, 2025");
  });

  it("S5: an error row reads 'Could not evaluate since Sep 19'", async () => {
    await renderOverview(setLatest(beforeF, EMAIL, (l) => ({ ...l, since: S1_SINCE })));
    expect(text(since(EMAIL))).toBe("Could not evaluate since Sep 19");
  });

  it("S6: the last-evaluated note reads 'failing since 10:05 today'", async () => {
    await renderOverview(
      setLatest(beforeF, EMAIL, (l) => {
        if (l.last_evaluated === null) throw new Error("fixture has no last_evaluated");
        return { ...l, last_evaluated: { ...l.last_evaluated, outcome: "fail", since: S2_SINCE } };
      }),
    );
    const note = rowFor(EMAIL).querySelector(".last-evaluated");
    expect(text(note ?? rowFor(EMAIL))).toMatch(/^Last evaluated: Fail, \d+ hours? ago; failing since 10:05 today$/);
  });

  it.each([
    ["the overview, recorded", (): Promise<unknown> => renderOverview(recorded)],
    ["the overview, A B E", (): Promise<unknown> => renderOverview(beforeF)],
    ["the overview, interrupted", (): Promise<unknown> => renderOverview(interrupted)],
    [
      "the check page, A B E",
      (): Promise<unknown> => renderCheck(EMAIL, { check: ok(detailOf(beforeF, EMAIL)), history: ok(emailHistoryBeforeF) }),
    ],
    [
      "the check page, interrupted",
      (): Promise<unknown> => renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(emailHistory) }),
    ],
  ])("S7: on %s, no 'since … ago'", async (_, show) => {
    await show();
    // Markup, so `[^<]` keeps a match inside one element's text.
    const markup = new XMLSerializer().serializeToString(document.body);
    expect(markup).toMatch(/since/i);
    expect(markup).not.toMatch(/since [^<]*ago/i);
    expect(markup).toMatch(/\bago\b/);
  });

  it("S8: a since that is not a timestamp reads 'an unknown time'", async () => {
    await renderOverview(setLatest(recorded, FAIL_ID, (l) => ({ ...l, since: "garbage" })));
    expect(text(since(FAIL_ID))).toBe("Failing since an unknown time");
    expect(text(rowFor(FAIL_ID))).not.toMatch(/NaN|Invalid/);
  });

  it("S9: 30 seconds in the future, the same local day, reads the time and 'today'", async () => {
    await renderOverview(setLatest(recorded, FAIL_ID, (l) => ({ ...l, since: "2026-09-26T12:00:30Z" })));
    expect(text(since(FAIL_ID))).toBe("Failing since 20:00 today");
  });
});

describe("R: checks the latest run counted that are not loaded now (P3)", () => {
  it("R1: a broken file: the banner says how many, after 'may be missing'", async () => {
    await renderOverview(runState({ ok: false, total: 18, loaded: 15, inRun: 15 }));
    const content = text(banner());
    const sentence =
      "The latest run checked 3 checks that are not loaded now. Its counts include them; the summary's do not.";
    expect(content).toContain(sentence);
    expect(content.indexOf(sentence)).toBeGreaterThan(content.indexOf("may be missing"));
    const paragraphs = Array.from(banner().querySelectorAll("p")).map((p) => text(p));
    const may = paragraphs.findIndex((p) => p.includes("may be missing"));
    expect(paragraphs[may + 1]).toBe(sentence);
  });

  it("R2: the run panel says it quietly under 'This run: 18 checks'", async () => {
    await renderOverview(runState({ ok: false, total: 18, loaded: 15, inRun: 15 }));
    const caption = panel().querySelector(".run-counts__caption");
    expect(text(caption ?? panel())).toBe("This run: 18 checks");
    const note = within(panel()).getByText("3 of them are not loaded now.");
    expect(note.className).toContain("quiet");
    expect(caption?.nextElementSibling).toBe(note);
    expect(text(panel())).not.toMatch(/edited or removed/);
  });

  it("R3: ok true, one edited: no banner; the panel says it was edited or removed", async () => {
    await renderOverview(runState({ ok: true, total: 18, loaded: 17, inRun: 17 }));
    expect(screen.queryByRole("region", { name: /check files? ha(s|ve) errors/ })).toBeNull();
    expect(text(panel())).toContain("1 of them is not loaded now. It was edited or removed since the run.");
  });

  it("R4: a run of one folder, all loaded: no sentence anywhere", async () => {
    await renderOverview(runState({ ok: false, total: 4, loaded: 15, inRun: 4 }));
    expect(document.body.textContent).not.toMatch(/not loaded now/);
    expect(text(panel())).toContain("This run: 4 checks");
  });

  it("R5: no runs recorded: no sentence, and the empty text as before", async () => {
    await renderOverview(noRunsState);
    expect(document.body.textContent).not.toMatch(/not loaded now/);
    expect(text(panel())).toContain("No runs are recorded for this project yet");
  });

  it("R6: counts.total below the matching checks: no sentence, no negative number", async () => {
    await renderOverview(runState({ ok: false, total: 10, loaded: 15, inRun: 15 }));
    expect(document.body.textContent).not.toMatch(/not loaded now/);
    expect(document.body.textContent).not.toMatch(/-\d+ (of them|checks?)/);
  });

  it("R7: k = 1 reads in the singular", async () => {
    await renderOverview(runState({ ok: false, total: 16, loaded: 15, inRun: 15 }));
    expect(text(banner())).toContain(
      "The latest run checked 1 check that is not loaded now. Its counts include it; the summary's do not.",
    );
    expect(text(panel())).toContain("1 of them is not loaded now.");
  });
});
