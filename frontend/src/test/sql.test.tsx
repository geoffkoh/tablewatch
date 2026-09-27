/**
 * The check page's SQL section, scenario by scenario (spec 005, P1–P15 and
 * S9 as the page sees it). Every API response is a fixture typed against the
 * generated contract.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { CheckDetail, CheckSql } from "../api/types";
import { COPIED_MS } from "../components/CopyButton";
import { brokenState } from "./fixtures/derived";
import { detailOf, emailHistory, editedPending, EDITED_ID, page, recordedHistory } from "./fixtures/detail";
import {
  BROKEN_SQL,
  DUPLICATES_SQL,
  EMAIL_SQL,
  FRESHNESS_SQL,
  genericSql,
  HOSTILE_CONDITION,
  HOSTILE_SQL,
  INVISIBLE_CONDITION,
  INVISIBLE_SQL,
  REMOTE_EVENTS_SQL,
  SCAN_AND_QUERY_SQL,
  SCHEMA_SQL,
  UNKNOWN_KIND_SQL,
  VOLUME_SQL,
} from "./fixtures/sql";
import { interrupted, recorded } from "./fixtures/states";
import { CLOCK, checkUrls, notFound, ok, renderCheck, setClock, stubCheckServer, text, UNAVAILABLE, type Answer } from "./render";

const EMAIL = "b1ceb8262d8b5441";
const DUPLICATES = "af0289a72fedd946";
const SCHEMA = "fbc3aa0b93b66eee";
const VOLUME = "32867fbe86f483f3";
const FRESHNESS = "a81b0374b0b04f06";

const INTERNAL: Answer = {
  status: 500,
  body: { error: { code: "internal_error", message: "internal error — see the server log" } },
};

// ---- the clipboard, stubbed per test ----------------------------------------

const writeText = vi.fn<(text: string) => Promise<void>>();

function setSecure(secure: boolean): void {
  Object.defineProperty(window, "isSecureContext", { value: secure, configurable: true });
  Object.defineProperty(navigator, "clipboard", { value: secure ? { writeText } : undefined, configurable: true });
}

beforeEach(() => {
  setClock(CLOCK);
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  setSecure(true);
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

// ---- helpers ----------------------------------------------------------------

function sqlSection(): HTMLElement {
  return screen.getByRole("region", { name: "SQL" });
}

function blocks(): HTMLPreElement[] {
  return Array.from(sqlSection().querySelectorAll("pre"));
}

/** A loaded check's detail, for ids the spec 004 fixtures know. */
function detail(id: string, state = recorded): CheckDetail {
  return detailOf(state, id);
}

/** A detail for a check the spec 004 fixtures lack, built from one they have. */
function detailLike(id: string, fields: Partial<CheckDetail>): CheckDetail {
  return { ...detailOf(recorded, "32c8f939b90f6367"), id, ...fields };
}

async function renderSql(id: string, sql: CheckSql | Answer, check?: CheckDetail): Promise<void> {
  const answer: Answer = typeof sql === "object" && "check_id" in sql ? ok(sql) : (sql as Answer);
  await renderCheck(id, { check: ok(check ?? detail(id)), history: ok(historyOf(id)), sql: answer });
}

/** The recorded history for ids the fixtures know; none for the rest. */
function historyOf(id: string): ReturnType<typeof page> {
  return recorded.checks.items.some((c) => c.id === id) ? recordedHistory(id) : page([]);
}

/** The section's words below its heading. */
function body(): string {
  return Array.from(sqlSection().children)
    .slice(1)
    .map(text)
    .join(" ");
}

function deferred(): { promise: Promise<Response>; resolve: (r: Response) => void } {
  let resolve: (r: Response) => void = () => undefined;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

// ---- P1 ---------------------------------------------------------------------

describe("P1: the SQL section", () => {
  it("names the dialect, the scan with its `;`, and this check's columns", async () => {
    await renderSql(EMAIL, EMAIL_SQL);
    const section = sqlSection();
    expect(within(section).getByRole("heading", { level: 2 }).textContent).toBe("SQL");
    expect(text(section)).toContain(
      "When tablewatch checks sales.customers on lake (duckdb), it reads the table once with this statement. " +
        "That one read computes 4 values, for this check and 3 others. This check uses:",
    );
    const uses = within(section).getAllByRole("listitem").map(text);
    expect(uses).toEqual([
      "m0 count(*), also used by 1 other check",
      "m1 sum(CASE WHEN (email IS NULL OR email IN ('', 'N/A')) THEN 1 ELSE 0 END)",
    ]);
    const [block] = blocks();
    expect(block?.textContent).toBe(`${EMAIL_SQL.statements[0]?.sql ?? ""};`);
    expect(block?.classList.contains("code-block")).toBe(true);
    expect(text(section)).toContain(
      "Built from the check files as loaded, for a run of every check on sales.customers. Results do not store " +
        "their SQL; a result recorded before these files were loaded may have used different SQL.",
    );
  });

  it("counts other checks in the plural (S4: Order volume)", async () => {
    await renderSql(VOLUME, VOLUME_SQL);
    expect(text(sqlSection())).toContain("That one read computes 6 values, for this check and 6 others.");
    expect(within(sqlSection()).getAllByRole("listitem").map(text)).toEqual(["m0 count(*), also used by 2 other checks"]);
  });

  it("says 'for this check only' and '1 value' when nothing else shares the scan", async () => {
    await renderSql(EMAIL, genericSql(EMAIL));
    expect(text(sqlSection())).toContain("That one read computes 1 value, for this check only.");
    expect(text(sqlSection())).not.toContain("also used by");
  });

  it("a query of the check's own: its sentence, its block and no scan (S2)", async () => {
    await renderSql(DUPLICATES, DUPLICATES_SQL, detailLike(DUPLICATES, { dataset: "sales.customers" }));
    expect(text(sqlSection())).toContain("This check sends its own statement to sales.customers on lake (duckdb).");
    expect(text(sqlSection())).not.toContain("other checks use the same statement");
    expect(text(sqlSection())).not.toContain("reads the table once");
    expect(blocks().map((b) => b.textContent)).toEqual([`${DUPLICATES_SQL.statements[0]?.sql ?? ""};`]);
    expect(text(sqlSection())).toContain("Built from the check files as loaded. Results do not store their SQL");
  });

  it("the scan, then the check's own query, in run order (S10)", async () => {
    await renderSql(EMAIL, SCAN_AND_QUERY_SQL);
    const kinds = Array.from(sqlSection().querySelectorAll("[data-kind]")).map((e) => e.getAttribute("data-kind"));
    expect(kinds).toEqual(["scan", "query"]);
    expect(text(sqlSection())).toContain("2 other checks use the same statement.");
    expect(blocks()[1]?.textContent).toContain("WHERE email IS NOT NULL GROUP BY email");
  });

  it("sits below the history table, open: no <details>", async () => {
    await renderSql(EMAIL, EMAIL_SQL);
    const history = screen.getByRole("region", { name: "History" });
    expect(history.compareDocumentPosition(sqlSection()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.querySelector("details, summary")).toBeNull();
    expect(sqlSection().id).toBe("sql");
  });

  it("requests /checks/{id}/sql with the id encoded", async () => {
    expect(checkUrls("orders:volume").sql).toBe("/api/v1/checks/orders%3Avolume/sql");
  });
});

// ---- the wording guard (P1, P5) ------------------------------------------------

const GUARD = [/\bproduced\b/i, /\blatest\b/i, /\bthis result\b/i, /\bran\b/i, /\bexecuted\b/i];

describe("P1/P5: the SQL section never claims a result", () => {
  const cases: [string, string, CheckSql | Answer, CheckDetail | undefined][] = [
    ["percent scan", EMAIL, EMAIL_SQL, undefined],
    ["shared scan", VOLUME, VOLUME_SQL, undefined],
    ["duration scan", FRESHNESS, FRESHNESS_SQL, undefined],
    ["own query", DUPLICATES, DUPLICATES_SQL, detailLike(DUPLICATES, {})],
    ["schema", SCHEMA, SCHEMA_SQL, undefined],
    ["scan and query", EMAIL, SCAN_AND_QUERY_SQL, undefined],
    ["unknown kind", EMAIL, UNKNOWN_KIND_SQL, undefined],
    ["cannot compile", "0e7e5c0de0e7e5c0", REMOTE_EVENTS_SQL, detailLike("0e7e5c0de0e7e5c0", { dataset: "events" })],
    ["broken", "8e3148f570b166f3", BROKEN_SQL, detailLike("8e3148f570b166f3", { dataset: "sales.lost", datasource: "" })],
    ["generic", EMAIL, genericSql(EMAIL), undefined],
    ["request failed", EMAIL, INTERNAL, undefined],
    ["404 while the check is loaded", EMAIL, notFound(), undefined],
  ];
  it.each(cases)("%s", async (_, id, sql, check) => {
    await renderSql(id, sql, check);
    const words = text(sqlSection());
    for (const pattern of GUARD) expect(words, String(pattern)).not.toMatch(pattern);
  });

  it("edited-pending: says 'as loaded' and passes the guard although the latest result used an older rule", async () => {
    await renderCheck(EDITED_ID, {
      check: ok(editedPending.check),
      history: ok(editedPending.history),
      sql: ok({ ...EMAIL_SQL, check_id: EDITED_ID }),
    });
    expect(document.querySelector('[data-note="judged-by"]')).not.toBeNull();
    const words = text(sqlSection());
    expect(words).toContain("as loaded");
    for (const pattern of GUARD) expect(words, String(pattern)).not.toMatch(pattern);
  });

  it("not loaded (P6)", async () => {
    await renderCheck(EMAIL, { check: notFound(), history: ok(emailHistory) });
    const words = text(sqlSection());
    for (const pattern of GUARD) expect(words, String(pattern)).not.toMatch(pattern);
  });
});

// ---- P2, P3 -------------------------------------------------------------------

describe("P2: a schema check", () => {
  it("has no SQL block and says why", async () => {
    await renderSql(SCHEMA, SCHEMA_SQL);
    expect(blocks()).toHaveLength(0);
    expect(within(sqlSection()).queryByRole("button")).toBeNull();
    expect(body()).toBe(
      "This check reads the list of columns in sales.orders and their types from the database. It reads no rows, so it has no SQL.",
    );
  });

  it("a schema lookup next to statements: the statements, then the lookup without 'no SQL'", async () => {
    await renderSql(SCHEMA, { ...SCHEMA_SQL, statements: VOLUME_SQL.statements });
    expect(blocks()).toHaveLength(1);
    expect(text(sqlSection())).toContain("This check reads the list of columns in sales.orders and their types from the database.");
    expect(text(sqlSection())).not.toContain("so it has no SQL");
  });

  it("no statement, no lookup, no error: says so", async () => {
    await renderSql(EMAIL, { ...EMAIL_SQL, statements: [] });
    expect(body()).toBe("This check sends no statement of its own.");
  });
});

describe("P3: cannot compile", () => {
  it("remote, events: 'Cannot compile' with the error in a monospace block; the rest renders; no alert", async () => {
    const id = REMOTE_EVENTS_SQL.check_id;
    await renderSql(id, REMOTE_EVENTS_SQL, detailLike(id, { dataset: "events", datasource: "wh" }));
    expect(text(sqlSection())).toContain("Cannot compile");
    expect(blocks().map((b) => b.textContent)).toEqual([REMOTE_EVENTS_SQL.error]);
    expect(within(sqlSection()).queryByRole("button")).toBeNull();
    expect(screen.getByRole("region", { name: "Rule" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "History" })).toBeTruthy();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
  });

  it("broken, 8e3148f570b166f3: the fixed message, several lines kept; no page-level error", async () => {
    const id = "8e3148f570b166f3";
    const multi = { ...BROKEN_SQL, error: `${BROKEN_SQL.error ?? ""}\nsecond line` };
    stubCheckServer(
      id,
      { check: ok(detailLike(id, { dataset: "sales.lost", datasource: "" })), history: ok(page([])), sql: ok(multi) },
      brokenState,
    );
    render(<App path={`/checks/${id}`} />);
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    expect(blocks()[0]?.textContent).toBe(multi.error);
    expect(blocks()[0]?.classList.contains("code-block--error")).toBe(true);
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
  });
});

// ---- P6, P7 -------------------------------------------------------------------

describe("P6: a check that is no longer loaded", () => {
  it("/checks and /sql 404, /history 200: one line, no request error", async () => {
    await renderCheck(EMAIL, { check: notFound(), history: ok(emailHistory), sql: notFound() });
    expect(body()).toBe("SQL is not available: this check is not in the loaded check files.");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
  });

  it("/checks and /history both 404: the not-found panel, no SQL section", async () => {
    await renderCheck("no-such-check", { check: notFound(), history: notFound(), sql: notFound() });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Check not found");
    expect(screen.queryByRole("region", { name: "SQL" })).toBeNull();
  });
});

describe("P7: one failure stays in its section", () => {
  it.each([
    ["500", INTERNAL, "internal error — see the server log"],
    ["network", "network-error" as const, "Could not reach the tablewatch server"],
  ])("/sql %s: only the SQL section shows it, worded for a section", async (_, answer, message) => {
    await renderSql(EMAIL, answer, detail(EMAIL, interrupted));
    const alert = screen.getByRole("alert");
    expect(sqlSection().contains(alert)).toBe(true);
    expect(within(alert).getByRole("heading", { level: 3 }).textContent).toBe("The SQL could not be loaded.");
    expect(text(alert)).toContain(message);
    expect(text(alert)).not.toContain("Nothing below");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("missing_percent(email) < 5%");
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Could not load everything.");
  });

  it("a 404 from /sql while /checks/{id} is 200 is a failure, not 'no longer loaded'", async () => {
    await renderSql(EMAIL, notFound());
    expect(sqlSection().contains(screen.getByRole("alert"))).toBe(true);
    expect(text(sqlSection())).not.toContain("not in the loaded check files");
  });

  it("Try again reloads /sql with the rest", async () => {
    await renderSql(EMAIL, INTERNAL);
    const fetchMock = stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(recordedHistory(EMAIL)), sql: ok(EMAIL_SQL) });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => {
      expect(blocks()).toHaveLength(1);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain(checkUrls(EMAIL).sql);
  });

  it("drops a /sql answer that lands after a later Refresh", async () => {
    await renderSql(EMAIL, EMAIL_SQL);
    const slow = deferred();
    const urls = checkUrls(EMAIL);
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (String(input) === urls.sql ? slow.promise : base(input))));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(recordedHistory(EMAIL)), sql: ok(VOLUME_SQL) });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
      expect(text(sqlSection())).toContain("sales.orders");
    });
    const late: CheckSql = { ...EMAIL_SQL, dataset: "late.answer" };
    await act(async () => {
      slow.resolve(new Response(JSON.stringify(late), { status: 200 }));
      await slow.promise;
    });
    expect(text(sqlSection())).not.toContain("late.answer");
    expect(text(sqlSection())).toContain("sales.orders");
  });
});

// ---- P8, P14, P15 ---------------------------------------------------------------

describe("P8: text is text", () => {
  it("an HTML-looking condition appears literally and creates no element", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    await renderSql("ed669ca6e5532a59", HOSTILE_SQL);
    expect(blocks()[0]?.textContent).toContain(HOSTILE_CONDITION);
    expect(text(sqlSection())).toContain(HOSTILE_CONDITION);
    expect(document.querySelectorAll("img, script, iframe")).toHaveLength(0);
    expect(document.querySelectorAll("[onerror]")).toHaveLength(0);
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("P14: invisible characters are marked", () => {
  it("marks U+202E and U+200B in place, keeps the text exact, and copies the exact bytes", async () => {
    await renderSql("ed669ca6e5532a59", INVISIBLE_SQL);
    const [block] = blocks();
    const expected = `${INVISIBLE_SQL.statements[0]?.sql ?? ""};`;
    expect(block?.textContent).toBe(expected);
    const marks = Array.from(block?.querySelectorAll(".invisible-char") ?? []);
    expect(marks.map((m) => m.getAttribute("data-cp"))).toEqual(["U+202E", "U+200B"]);
    expect(marks.map((m) => m.textContent)).toEqual(["‮", "​"]);
    // the column list marks them too
    expect(sqlSection().querySelectorAll("li .invisible-char")).toHaveLength(2);
    expect(text(sqlSection())).toContain(INVISIBLE_CONDITION.replace(/\s+/g, " ").trim().slice(0, 10));
    fireEvent.click(screen.getByRole("button", { name: "Copy the scan" }));
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expected);
    });
  });
});

describe("P15: an unknown statement kind is skipped", () => {
  it("renders the scan and the query, nothing for the unknown kind, and no error", async () => {
    await renderSql(EMAIL, UNKNOWN_KIND_SQL);
    const kinds = Array.from(sqlSection().querySelectorAll("[data-kind]")).map((e) => e.getAttribute("data-kind"));
    expect(kinds).toEqual(["scan", "query"]);
    expect(blocks()).toHaveLength(2);
    expect(text(sqlSection())).not.toContain("WHERE email IS NULL");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// ---- P9 -------------------------------------------------------------------------

describe("P9: copy", () => {
  it("'Copy the scan' copies the API's sql plus ';', which is what the block shows", async () => {
    await renderSql(EMAIL, EMAIL_SQL);
    const expected = `${EMAIL_SQL.statements[0]?.sql ?? ""};`;
    fireEvent.click(screen.getByRole("button", { name: "Copy the scan" }));
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(expected);
    });
    expect(blocks()[0]?.textContent).toBe(expected);
  });

  it("'Copy the query' copies the query", async () => {
    await renderSql(EMAIL, SCAN_AND_QUERY_SQL);
    fireEvent.click(screen.getByRole("button", { name: "Copy the query" }));
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(`${SCAN_AND_QUERY_SQL.statements[1]?.sql ?? ""};`);
    });
  });

  it("says 'Copied' in a polite live region for about two seconds", async () => {
    await renderSql(EMAIL, EMAIL_SQL);
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    vi.setSystemTime(new Date(CLOCK));
    const live = sqlSection().querySelector('[aria-live="polite"]');
    expect(live?.textContent).toBe("");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy the scan" }));
      await Promise.resolve();
    });
    expect(live?.textContent).toBe("Copied");
    act(() => {
      vi.advanceTimersByTime(COPIED_MS - 100);
    });
    expect(live?.textContent).toBe("Copied");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(live?.textContent).toBe("");
  });

  it("says how to copy by hand when the clipboard refuses", async () => {
    writeText.mockRejectedValue(new Error("denied"));
    await renderSql(EMAIL, EMAIL_SQL);
    fireEvent.click(screen.getByRole("button", { name: "Copy the scan" }));
    await vi.waitFor(() => {
      expect(text(sqlSection())).toContain("Could not copy. Select the text and copy it.");
    });
  });

  it("where copying is unavailable, 'Select all' selects the block's text", async () => {
    setSecure(false);
    await renderSql(EMAIL, EMAIL_SQL);
    expect(within(sqlSection()).queryByRole("button", { name: /^Copy/ })).toBeNull();
    const button = within(sqlSection()).getByRole("button", { name: "Select all of the scan" });
    expect(button.textContent).toBe("Select all");
    fireEvent.click(button);
    expect(window.getSelection()?.toString()).toBe(`${EMAIL_SQL.statements[0]?.sql ?? ""};`);
    expect(writeText).not.toHaveBeenCalled();
  });
});

// ---- P10 ------------------------------------------------------------------------

describe("P10: how the value is computed", () => {
  it("percent: counts, and tablewatch computes the percentage", async () => {
    await renderSql(EMAIL, EMAIL_SQL);
    expect(text(sqlSection())).toContain("The database returns counts; tablewatch computes the percentage from them.");
  });

  it("duration: a timestamp, and how long ago at the time of each run", async () => {
    await renderSql(FRESHNESS, FRESHNESS_SQL);
    expect(text(sqlSection())).toContain(
      "The database returns a timestamp; tablewatch computes how long ago it was at the time of each run, so the same data looks older the later the run.",
    );
  });

  it("count: no sentence", async () => {
    await renderSql(VOLUME, VOLUME_SQL);
    expect(sqlSection().querySelector('[data-sql-note="computed"]')).toBeNull();
  });

  it("schema: P2's sentence instead", async () => {
    await renderSql(SCHEMA, SCHEMA_SQL);
    expect(sqlSection().querySelector('[data-sql-note="computed"]')).toBeNull();
  });
});

// ---- P11 ------------------------------------------------------------------------

describe("P11: link to the section", () => {
  it("/checks/<id>#sql scrolls to the section once, after the first round settles", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.history.replaceState(null, "", `/checks/${EMAIL}#sql`);
    await renderSql(EMAIL, EMAIL_SQL);
    await vi.waitFor(() => {
      expect(scroll).toHaveBeenCalledTimes(1);
    });
    expect(scroll.mock.contexts[0]).toBe(sqlSection());
    stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(recordedHistory(EMAIL)), sql: ok(EMAIL_SQL) });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    expect(scroll).toHaveBeenCalledTimes(1);
  });

  it("without the fragment, nothing scrolls", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    await renderSql(EMAIL, EMAIL_SQL);
    expect(scroll).not.toHaveBeenCalled();
  });
});

// ---- P12 ------------------------------------------------------------------------

describe("P12: long lines", () => {
  it("each block is a focusable, labelled region", async () => {
    await renderSql(EMAIL, SCAN_AND_QUERY_SQL);
    for (const block of blocks()) {
      expect(block.getAttribute("role")).toBe("region");
      expect(block.tabIndex).toBe(0);
    }
    expect(screen.getByRole("region", { name: "The scan, duckdb" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "The query, duckdb" })).toBeTruthy();
  });
});

// ---- P13 (S9 on the page) ----------------------------------------------------------

describe("P13: the store is down, the SQL is not", () => {
  it("/checks and /history 503, /sql 200: the section renders in full, without P10's sentence", async () => {
    await renderCheck(EMAIL, { check: UNAVAILABLE, history: UNAVAILABLE, sql: ok(EMAIL_SQL) });
    const section = sqlSection();
    expect(text(section)).toContain("When tablewatch checks sales.customers on lake (duckdb)");
    expect(blocks()).toHaveLength(1);
    expect(section.querySelector('[data-sql-note="computed"]')).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(section.contains(alerts[0] ?? null)).toBe(false);
    expect(text(alerts[0] ?? document.body)).toContain("results store: unavailable");
  });
});

// ---- source rules for the clipboard (P9) ---------------------------------------------

const SOURCES = import.meta.glob<string>("../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true });
// Built from parts so this file does not match its own patterns.
const j = (...parts: string[]): string => parts.join("");

describe("P9: clipboard source rules", () => {
  const app = Object.entries(SOURCES).filter(([p]) => !p.startsWith("./"));

  it("only lib/clipboard.ts touches navigator.clipboard", () => {
    const touching = app.filter(([, s]) => new RegExp(j("\\.clip", "board\\b")).test(s)).map(([p]) => p);
    expect(touching).toEqual(["../lib/clipboard.ts"]);
  });

  it("has no execCommand fallback", () => {
    expect(app.filter(([, s]) => new RegExp(j("exec", "Command")).test(s)).map(([p]) => p)).toEqual([]);
  });
});
