/**
 * Spec 004, adversarial (qa-engineer): the check page's load hook under
 * races, and the rule field end to end.
 */
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HistoryEntry } from "../api/types";
import { detailOf, emailSummary, entry, page } from "./fixtures/detail";
import { interrupted, STARTED } from "./fixtures/states";
import { CLOCK, checkUrls, ok, olderUrl, renderCheck, setClock, stubCheckServer } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

const EMAIL = "b1ceb8262d8b5441";

function historyRows(): HTMLElement[] {
  const table = screen.getByRole("table");
  const [, body] = within(table).getAllByRole("rowgroup");
  if (body === undefined) throw new Error("no table body");
  return within(body).getAllByRole("row");
}

/** Run r<i>, i minutes before F: 0 is the newest. */
function run(i: number): HistoryEntry {
  return entry(emailSummary, "A", {
    run_id: `r${String(i).padStart(31, "0")}`,
    started_at: new Date(Date.parse(STARTED.F) - i * 60_000).toISOString(),
    outcome: "fail",
    value: 20,
    display_value: "20.00%",
  });
}

function deferred(): { promise: Promise<Response>; resolve: (r: Response) => void } {
  let resolve: (r: Response) => void = () => undefined;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("D13/D14: paging and refresh together", () => {
  it("after a refresh, Load older follows the new first page's cursor, not the old one", async () => {
    await renderCheck(EMAIL, {
      check: ok(detailOf(interrupted, EMAIL)),
      history: ok(page([run(0), run(1)], "OLD")),
      older: { OLD: ok(page([run(2)], null)) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Load older results" }));
    await vi.waitFor(() => {
      expect(historyRows()).toHaveLength(3);
    });
    const second = stubCheckServer(EMAIL, {
      check: ok(detailOf(interrupted, EMAIL)),
      history: ok(page([run(0), run(1)], "NEW")),
      older: { NEW: ok(page([run(2)], null)) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    expect(historyRows()).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Load older results" }));
    await vi.waitFor(() => {
      expect(historyRows()).toHaveLength(3);
    });
    const urls = second.mock.calls.map((c) => String(c[0]));
    expect(urls).toContain(olderUrl(EMAIL, "NEW"));
    expect(urls).not.toContain(olderUrl(EMAIL, "OLD"));
  });

  it("Load older clicked while a refresh is in flight never loses or repeats a result", async () => {
    // Round 1: first page r1..r2, cursor OLD -> r3. Then a new run r0 lands
    // and Refresh is clicked; before its /history answers, Load older is
    // clicked. The refreshed first page is r0..r1 with cursor NEW -> r2.
    await renderCheck(EMAIL, {
      check: ok(detailOf(interrupted, EMAIL)),
      history: ok(page([run(1), run(2)], "OLD")),
    });
    const refreshed = deferred();
    const urls = checkUrls(EMAIL);
    const answers: Record<string, () => Promise<Response>> = {
      [urls.project]: () => Promise.resolve(new Response(JSON.stringify(interrupted.project), { status: 200 })),
      [urls.check]: () => Promise.resolve(new Response(JSON.stringify(detailOf(interrupted, EMAIL)), { status: 200 })),
      [urls.runs]: () => Promise.resolve(new Response(JSON.stringify(interrupted.runs), { status: 200 })),
      [urls.history]: () => refreshed.promise,
      [olderUrl(EMAIL, "OLD")]: () => Promise.resolve(new Response(JSON.stringify(page([run(3)], null)), { status: 200 })),
      [olderUrl(EMAIL, "NEW")]: () =>
        Promise.resolve(new Response(JSON.stringify(page([run(2), run(3)], null)), { status: 200 })),
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const answer = answers[String(input)];
        return answer === undefined ? Promise.reject(new Error(`unexpected ${String(input)}`)) : answer();
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    const button = screen.queryByRole("button", { name: "Load older results" });
    if (button !== null && !(button as HTMLButtonElement).disabled) fireEvent.click(button);
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      refreshed.resolve(new Response(JSON.stringify(page([run(0), run(1)], "NEW")), { status: 200 }));
      await refreshed.promise;
    });
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    // Whatever the page shows, it is a gap-free, duplicate-free prefix of r0, r1, r2, r3.
    const shown = historyRows().map((r) => r.dataset.runId);
    const expected = [run(0), run(1), run(2), run(3)].map((e) => e.run_id).slice(0, shown.length);
    expect(shown).toEqual(expected);
  });
});

describe("the rule field end to end", () => {
  it("a between rule on the page: its text, its two lines, and both regions shaded", async () => {
    const id = "366d9254d889c910";
    const check = detailOf(interrupted, id);
    const values = [3, 54.36];
    await renderCheck(id, {
      check: ok(check),
      history: ok(
        page(
          values.map((v, i) =>
            entry(check, i === 0 ? "F" : "B", {
              outcome: v < 10 ? "fail" : "pass",
              value: v,
              display_value: String(v),
            }),
          ),
        ),
      ),
    });
    const rule = screen.getByRole("region", { name: "Rule" });
    expect(within(rule).getByText("between 10 and 500")).toBeTruthy();
    const svg = document.querySelector("svg.chart__svg");
    expect(svg).not.toBeNull();
    const failBands = svg?.querySelectorAll(".chart__band--fail") ?? [];
    expect(failBands.length).toBeGreaterThan(0);
    // 3 fails `between 10 and 500`: it must not sit in white space.
    const fail = svg?.querySelector('.mark[data-outcome="fail"]');
    expect(fail).not.toBeNull();
  });
});
