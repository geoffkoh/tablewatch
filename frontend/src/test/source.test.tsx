/**
 * The check page's Source section, scenario by scenario (spec 006, P4–P16).
 * Every API response is a fixture typed against the generated contract; the
 * `retail` and `commented` bodies were captured from the in-process app.
 * P16's 360 px behaviour and real text selection are the hand run's; here
 * only the class, attributes, region and CSS rules are checked.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { getCheckSource } from "../api/api";
import type { CheckDetail, CheckSource, CheckSql } from "../api/types";
import { Identity } from "../components/check/Identity";
import { MAX_DIGITS } from "../components/SourceBlock";
import { isInvisible } from "../lib/invisible";
import CSS from "../styles/app.css?raw";
import { detailOf, EDITED_ID, editedPending, emailHistory, page, recordedHistory } from "./fixtures/detail";
import {
  AVG_SOURCE,
  BOM_SOURCE,
  COMMENTED_VOLUME_SOURCE,
  COMMENTED_VOLUME_SOURCE_LOCATION,
  CUSTOM_SOURCE,
  EMAIL_SOURCE,
  FILTERED_SCHEMA_SOURCE,
  FLOW_SOURCE,
  HOSTILE_COMMENT,
  HOSTILE_SOURCE,
  INVISIBLE_SOURCE,
  INVISIBLE_TEXT,
  LOADED_AT,
  ROWS_SOURCE,
  SCHEMA_SOURCE,
  UNAVAILABLE_SOURCE,
  VOLUME_SOURCE,
} from "./fixtures/source";
import { EMAIL_SQL, REMOTE_EVENTS_SQL } from "./fixtures/sql";
import { recorded } from "./fixtures/states";
import { CLOCK, checkUrls, notFound, ok, renderCheck, setClock, stubCheckServer, text, UNAVAILABLE, type Answer } from "./render";

const EMAIL = "b1ceb8262d8b5441";
const ROWS = "32c8f939b90f6367";
const VOLUME = "32867fbe86f483f3";
const SCHEMA = "fbc3aa0b93b66eee";
const AVG = "4a831091035ca6c6";
const FLOW = "e3a77b3bf2c0c560";
const CUSTOM = "98cd31ce24b6afef";
const FILTERED_SCHEMA = "2f9a43de2ae47ba9";
const ONE = "ec91af87c6b3495e";

const INTERNAL: Answer = {
  status: 500,
  body: { error: { code: "internal_error", message: "internal error — see the server log" } },
};

const DEFAULTS_SENTENCE =
  "The dataset, datasource, owner and tags shown at the top of the page come from this file's first lines or a _defaults.yml.";

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

function sourceSection(): HTMLElement {
  return screen.getByRole("region", { name: "Source" });
}

function block(): HTMLPreElement {
  const pre = sourceSection().querySelector("pre");
  if (pre === null) throw new Error("no source block");
  return pre;
}

function code(): HTMLElement {
  const el = block().querySelector("code");
  if (el === null) throw new Error("no <code>");
  return el;
}

function numbers(): string[] {
  return Array.from(block().querySelectorAll(".line")).map((l) => l.getAttribute("data-line") ?? "?");
}

function caption(): HTMLElement {
  const found = sourceSection().querySelector<HTMLElement>('[data-source-note="as-loaded"]');
  if (found === null) throw new Error("no caption");
  return found;
}

function note(name: string): HTMLElement | null {
  return sourceSection().querySelector<HTMLElement>(`[data-source-note="${name}"]`);
}

/** The section's words outside the code block (P5): heading, caption, sentences, button. */
function wordsOutsideTheBlock(): string {
  const clone = sourceSection().cloneNode(true) as HTMLElement;
  for (const pre of Array.from(clone.querySelectorAll("pre"))) pre.remove();
  return text(clone);
}

/** A detail for a check the spec 004 fixtures lack, built from one they have. */
function detailLike(id: string, fields: Partial<CheckDetail> = {}): CheckDetail {
  return { ...detailOf(recorded, ROWS), id, ...fields };
}

/** The recorded history for ids the fixtures know; none for the rest. */
function historyOf(id: string): ReturnType<typeof page> {
  return recorded.checks.items.some((c) => c.id === id) ? recordedHistory(id) : page([]);
}

function detail(id: string): CheckDetail {
  return recorded.checks.items.some((c) => c.id === id) ? detailOf(recorded, id) : detailLike(id);
}

async function renderSource(
  id: string,
  source: CheckSource | Answer,
  options: { check?: CheckDetail | Answer; sql?: CheckSql; path?: string; project?: Answer } = {},
): Promise<void> {
  const answer: Answer = typeof source === "object" && "check_id" in source ? ok(source) : (source as Answer);
  const check = options.check ?? detail(id);
  const checkAnswer: Answer = typeof check === "object" && "id" in check ? ok(check) : (check as Answer);
  await renderCheck(
    id,
    {
      check: checkAnswer,
      history: ok(historyOf(id)),
      source: answer,
      ...(options.sql === undefined ? {} : { sql: ok(options.sql) }),
      ...(options.project === undefined ? {} : { project: options.project }),
    },
    options.path,
  );
}

// ---- the client ---------------------------------------------------------------

describe("getCheckSource", () => {
  it("requests /api/v1/checks/{id}/source with the id encoded", async () => {
    const mock = vi.fn((_input: RequestInfo | URL) => Promise.resolve(new Response(JSON.stringify(EMAIL_SOURCE), { status: 200 })));
    vi.stubGlobal("fetch", mock);
    expect(await getCheckSource("orders:volume")).toEqual(EMAIL_SOURCE);
    expect(mock.mock.calls[0]?.[0]).toBe("/api/v1/checks/orders%3Avolume/source");
  });
});

// ---- P4 -------------------------------------------------------------------------

describe("P4: the Source section", () => {
  it("32867fbe86f483f3 on retail: an open section, id=source, lines 5–8 numbered by data-line, below the SQL", async () => {
    await renderSource(VOLUME, VOLUME_SOURCE);
    const section = sourceSection();
    expect(section.id).toBe("source");
    expect(within(section).getByRole("heading", { level: 2 }).textContent).toBe("Source");
    expect(document.querySelector("details, summary")).toBeNull();
    const sql = screen.getByRole("region", { name: "SQL" });
    expect(sql.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(numbers()).toEqual(["5", "6", "7", "8"]);
    for (const line of Array.from(block().querySelectorAll("span.line"))) expect(line.tagName).toBe("SPAN");
    expect(block().querySelector("code")).not.toBeNull();
  });

  it("the <code>'s textContent is `text` exactly: the numbers are not in it", async () => {
    await renderSource(VOLUME, VOLUME_SOURCE);
    expect(code().textContent).toBe(VOLUME_SOURCE.text);
    expect(block().textContent).toBe(VOLUME_SOURCE.text);
  });

  it("the caption, exactly, with /source's own loaded_at in a <time>", async () => {
    await renderSource(VOLUME, VOLUME_SOURCE);
    expect(text(caption())).toBe("checks/sales/orders.yml, lines 5–8, from the check files as loaded 2 hours ago.");
    expect(caption().querySelector("code")?.textContent).toBe("checks/sales/orders.yml");
    const time = caption().querySelector("time");
    expect(time?.getAttribute("datetime")).toBe(LOADED_AT);
    expect(time?.textContent).toBe("2 hours ago");
  });

  it("the caption renders when /project fails", async () => {
    await renderSource(VOLUME, VOLUME_SOURCE, { project: INTERNAL });
    expect(text(caption())).toBe("checks/sales/orders.yml, lines 5–8, from the check files as loaded 2 hours ago.");
    expect(caption().querySelector("time")?.getAttribute("datetime")).toBe(LOADED_AT);
  });

  it("a one-line span: 'line 4'", async () => {
    await renderSource(ROWS, ROWS_SOURCE);
    expect(text(caption())).toBe("checks/sales/customers.yml, line 4, from the check files as loaded 2 hours ago.");
    expect(numbers()).toEqual(["4"]);
  });

  it("the last check in a file (Y3): lines 18–20", async () => {
    await renderSource(SCHEMA, SCHEMA_SOURCE);
    expect(numbers()).toEqual(["18", "19", "20"]);
    expect(code().textContent).toBe(SCHEMA_SOURCE.text);
  });

  it("comments on `commented` (Y4): the comment line is numbered and shown", async () => {
    await renderSource(VOLUME, COMMENTED_VOLUME_SOURCE);
    expect(numbers()).toEqual(["10", "11", "12", "13", "14"]);
    expect(block().querySelector('[data-line="10"]')?.textContent).toBe("  # Volume alarm agreed with ops, 2026-09.\n");
  });

  it("a flow-style line shared by two checks: 'line 3' and no extra sentence", async () => {
    await renderSource(FLOW, FLOW_SOURCE);
    expect(text(caption())).toBe("checks/flow.yml, line 3, from the check files as loaded 2 hours ago.");
    const sentences = Array.from(sourceSection().querySelectorAll(":scope > p"))
      .filter((p) => !p.classList.contains("source__actions"))
      .map(text);
    expect(sentences).toEqual([text(caption()), DEFAULTS_SENTENCE]);
  });

  it("blank lines get their own numbered line, and the text stays exact (Y13's block scalar)", async () => {
    const refunds: CheckSource = {
      ...EMAIL_SOURCE,
      check_id: "d0ebb1527db76d0e",
      path: "checks/sales/refunds.yml",
      start_line: 3,
      end_line: 9,
      text: "  - sql_metric > 0:\n      name: Refund ratio\n      query: |\n        SELECT count(*)\n        FROM refunds\n\n        WHERE amount > 0",
    };
    await renderSource("d0ebb1527db76d0e", refunds);
    expect(numbers()).toEqual(["3", "4", "5", "6", "7", "8", "9"]);
    expect(block().querySelector('[data-line="8"]')?.textContent).toBe("\n");
    expect(code().textContent).toBe(refunds.text);
    expect(text(caption())).toContain("lines 3–9");
  });

  it("the last line holds no newline; every other line ends with one", async () => {
    await renderSource(VOLUME, VOLUME_SOURCE);
    const lines = Array.from(block().querySelectorAll(".line")).map((l) => l.textContent ?? "");
    expect(lines.slice(0, -1).every((l) => l.endsWith("\n"))).toBe(true);
    expect(lines.at(-1)).toBe("      fail: when = 0");
  });

  it.each([
    [VOLUME, VOLUME_SOURCE, "1"],
    [SCHEMA, SCHEMA_SOURCE, "2"],
  ])("the number column's width comes from end_line's digits (%s: data-digits %s)", async (id, source, digits) => {
    await renderSource(id, source);
    expect(block().getAttribute("data-digits")).toBe(digits);
  });

  it("caps data-digits at the widest column the CSS sets", async () => {
    await renderSource(EMAIL, { ...EMAIL_SOURCE, start_line: 12345678, end_line: 12345679 });
    expect(block().getAttribute("data-digits")).toBe(String(MAX_DIGITS));
    expect(CSS).toContain(`.code-block--lines[data-digits="${String(MAX_DIGITS)}"]`);
  });
});

// ---- P5 -------------------------------------------------------------------------

const GUARD = [/\bproduced\b/i, /\blatest\b/i, /\bthis result\b/i, /\bran\b/i, /\bexecuted\b/i];

describe("P5: the source is today's, the result may not be", () => {
  it("edited-pending: shows `< 25%` and says 'as loaded'", async () => {
    const pending: CheckSource = {
      ...EMAIL_SOURCE,
      check_id: EDITED_ID,
      text: "  - missing_percent(email) < 25%:\n      missing_values: ['', 'N/A']",
    };
    await renderCheck(EDITED_ID, { check: ok(editedPending.check), history: ok(editedPending.history), source: ok(pending) });
    expect(document.querySelector('[data-note="judged-by"]')).not.toBeNull();
    expect(code().textContent).toContain("missing_percent(email) < 25%");
    expect(text(caption())).toContain("as loaded");
    const words = wordsOutsideTheBlock();
    for (const pattern of GUARD) expect(words, String(pattern)).not.toMatch(pattern);
  });

  const cases: [string, string, CheckSource | Answer, CheckDetail | Answer | undefined][] = [
    ["options", EMAIL, EMAIL_SOURCE, undefined],
    ["trigger", VOLUME, VOLUME_SOURCE, undefined],
    ["one line", ROWS, ROWS_SOURCE, undefined],
    ["comments", VOLUME, COMMENTED_VOLUME_SOURCE, undefined],
    ["flow", FLOW, FLOW_SOURCE, undefined],
    ["filter applies", AVG, AVG_SOURCE, undefined],
    ["filter does not apply, sql_metric", CUSTOM, CUSTOM_SOURCE, detailLike(CUSTOM, { metric: "sql_metric" })],
    ["filter does not apply, schema", FILTERED_SCHEMA, FILTERED_SCHEMA_SOURCE, detailLike(FILTERED_SCHEMA, { metric: "schema" })],
    ["span unavailable", ONE, UNAVAILABLE_SOURCE, undefined],
    ["hostile comment", EMAIL, HOSTILE_SOURCE, undefined],
    ["invisible characters", EMAIL, INVISIBLE_SOURCE, undefined],
    ["request failed", EMAIL, INTERNAL, undefined],
    ["404 while the check is loaded", EMAIL, notFound(), undefined],
  ];
  it.each(cases)("the wording guard: %s", async (_, id, source, check) => {
    await renderSource(id, source, check === undefined ? {} : { check });
    const words = wordsOutsideTheBlock();
    for (const pattern of GUARD) expect(words, String(pattern)).not.toMatch(pattern);
  });

  it("the wording guard: not loaded (P6)", async () => {
    await renderCheck(EMAIL, { check: notFound(), history: ok(emailHistory) });
    const words = wordsOutsideTheBlock();
    for (const pattern of GUARD) expect(words, String(pattern)).not.toMatch(pattern);
  });

  it("the file's own lines are exempt: a comment may say 'latest'", async () => {
    await renderSource(EMAIL, { ...EMAIL_SOURCE, text: "  # the latest rule, produced by ops\n  - row_count > 0" });
    expect(code().textContent).toContain("latest");
    for (const pattern of GUARD) expect(wordsOutsideTheBlock(), String(pattern)).not.toMatch(pattern);
  });
});

// ---- P6, P7 -------------------------------------------------------------------

describe("P6: a check that is no longer loaded", () => {
  it("/checks and /source 404, /history 200: one line, no filter sentences, no alert", async () => {
    await renderCheck(EMAIL, { check: notFound(), history: ok(emailHistory), source: notFound() });
    expect(Array.from(sourceSection().querySelectorAll(":scope > p")).map(text)).toEqual([
      "The source is not available: this check is not in the loaded check files.",
    ]);
    expect(note("filter")).toBeNull();
    expect(note("defaults")).toBeNull();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
  });

  it("/checks and /history both 404: the not-found panel, no Source section", async () => {
    await renderCheck("no-such-check", { check: notFound(), history: notFound(), source: notFound() });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Check not found");
    expect(screen.queryByRole("region", { name: "Source" })).toBeNull();
  });

  it("the section waits for /checks/{id}", async () => {
    let release: (r: Response) => void = () => undefined;
    const slow = new Promise<Response>((r) => {
      release = r;
    });
    stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(historyOf(EMAIL)) });
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (String(input) === checkUrls(EMAIL).check ? slow : base(input))));
    render(<App path={`/checks/${EMAIL}`} />);
    await vi.waitFor(() => {
      expect(screen.getAllByText("Loading…").length).toBeGreaterThan(0);
    });
    expect(screen.queryByRole("region", { name: "Source" })).toBeNull();
    await act(async () => {
      release(new Response(JSON.stringify(detail(EMAIL)), { status: 200 }));
      await slow;
    });
    await vi.waitFor(() => {
      expect(sourceSection()).toBeTruthy();
    });
  });
});

describe("P7: one failure stays in its section", () => {
  it.each([
    ["500", INTERNAL, "internal error — see the server log"],
    ["network", "network-error" as const, "Could not reach the tablewatch server"],
  ])("/source %s: only the Source section shows it; the status says so", async (_, answer, message) => {
    await renderSource(EMAIL, answer);
    const alert = screen.getByRole("alert");
    expect(sourceSection().contains(alert)).toBe(true);
    expect(within(alert).getByRole("heading", { level: 3 }).textContent).toBe("The source could not be loaded.");
    expect(text(alert)).toContain(message);
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(note("filter")).toBeNull();
    expect(note("defaults")).toBeNull();
    expect(screen.getByRole("region", { name: "SQL" }).querySelector("pre")).not.toBeNull();
    expect(screen.getByRole("status").textContent).toBe("Could not load everything.");
  });

  it("a 404 from /source while /checks/{id} is 200 is a failure, not 'no longer loaded'", async () => {
    await renderSource(EMAIL, notFound());
    expect(sourceSection().contains(screen.getByRole("alert"))).toBe(true);
    expect(text(sourceSection())).not.toContain("not in the loaded check files");
    expect(screen.getByRole("status").textContent).toBe("Could not load everything.");
  });

  it("/checks/{id} 404 and /source 500: a failure, not 'no longer loaded'", async () => {
    await renderCheck(EMAIL, { check: notFound(), history: ok(emailHistory), source: INTERNAL });
    expect(sourceSection().contains(screen.getByRole("alert"))).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("Could not load everything.");
  });

  it("Try again reloads /source with the rest", async () => {
    await renderSource(EMAIL, INTERNAL);
    const fetchMock = stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(historyOf(EMAIL)), source: ok(EMAIL_SOURCE) });
    fireEvent.click(within(sourceSection()).getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => {
      expect(code().textContent).toBe(EMAIL_SOURCE.text);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain(checkUrls(EMAIL).source);
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
  });

  it("drops a /source answer that lands after a later Refresh", async () => {
    await renderSource(EMAIL, EMAIL_SOURCE);
    let release: (r: Response) => void = () => undefined;
    const slow = new Promise<Response>((r) => {
      release = r;
    });
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (String(input) === checkUrls(EMAIL).source ? slow : base(input))));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(historyOf(EMAIL)), source: ok(ROWS_SOURCE) });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
      expect(code().textContent).toBe(ROWS_SOURCE.text);
    });
    await act(async () => {
      release(new Response(JSON.stringify({ ...EMAIL_SOURCE, text: "  - late answer" }), { status: 200 }));
      await slow;
    });
    expect(code().textContent).toBe(ROWS_SOURCE.text);
  });
});

// ---- P8 -------------------------------------------------------------------------

describe("P8: text is text", () => {
  it("a comment holding <script> and <img onerror> appears literally and creates no element", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    await renderSource(EMAIL, HOSTILE_SOURCE);
    expect(block().querySelector('[data-line="5"]')?.textContent).toBe(`${HOSTILE_COMMENT}\n`);
    expect(code().textContent).toBe(HOSTILE_SOURCE.text);
    expect(document.querySelectorAll("script, img, iframe")).toHaveLength(0);
    expect(document.querySelectorAll("[onerror]")).toHaveLength(0);
    expect(alert).not.toHaveBeenCalled();
  });
});

// ---- P9 -------------------------------------------------------------------------

describe("P9: copy", () => {
  it("'Copy the source' copies `text` exactly", async () => {
    await renderSource(VOLUME, VOLUME_SOURCE);
    fireEvent.click(within(sourceSection()).getByRole("button", { name: "Copy the source" }));
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(VOLUME_SOURCE.text);
    });
    await vi.waitFor(() => {
      expect(sourceSection().querySelector('[aria-live="polite"]')?.textContent).toBe("Copied");
    });
  });

  it("where copying is unavailable, 'Select all' selects the <code> only", async () => {
    setSecure(false);
    await renderSource(VOLUME, VOLUME_SOURCE);
    expect(within(sourceSection()).queryByRole("button", { name: /^Copy/ })).toBeNull();
    const button = within(sourceSection()).getByRole("button", { name: "Select all of the source" });
    fireEvent.click(button);
    const selection = window.getSelection();
    expect(selection?.toString()).toBe(VOLUME_SOURCE.text);
    const range = selection?.getRangeAt(0);
    expect(range?.commonAncestorContainer).toBe(code());
    expect(range?.intersectsNode(caption())).toBe(false);
    expect(writeText).not.toHaveBeenCalled();
  });

  it("no Copy button when the span is unavailable", async () => {
    await renderSource(ONE, UNAVAILABLE_SOURCE);
    expect(within(sourceSection()).queryByRole("button")).toBeNull();
  });
});

// ---- P11 ------------------------------------------------------------------------

describe("P11: #source", () => {
  it("/checks/<id>#source scrolls to the Source section once, after the first round settles", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.history.replaceState(null, "", `/checks/${EMAIL}#source`);
    await renderSource(EMAIL, EMAIL_SOURCE);
    await vi.waitFor(() => {
      expect(scroll).toHaveBeenCalledTimes(1);
    });
    expect(scroll.mock.contexts[0]).toBe(sourceSection());
    stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(historyOf(EMAIL)), source: ok(EMAIL_SOURCE) });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    expect(scroll).toHaveBeenCalledTimes(1);
  });

  it("#sql still scrolls to the SQL section", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.history.replaceState(null, "", `/checks/${EMAIL}#sql`);
    await renderSource(EMAIL, EMAIL_SOURCE);
    await vi.waitFor(() => {
      expect(scroll).toHaveBeenCalledTimes(1);
    });
    expect(scroll.mock.contexts[0]).toBe(screen.getByRole("region", { name: "SQL" }));
  });

  it.each(["#constructor", "#__proto__", "#Source", "#"])("%s scrolls nowhere", async (hash) => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.history.replaceState(null, "", `/checks/${EMAIL}${hash}`);
    await renderSource(EMAIL, EMAIL_SOURCE);
    expect(scroll).not.toHaveBeenCalled();
  });

  it("the identity panel's whole file:line:col links to #source (commented, 32867fbe86f483f3)", async () => {
    await renderSource(VOLUME, COMMENTED_VOLUME_SOURCE, { check: { ...detail(VOLUME), ...COMMENTED_VOLUME_SOURCE_LOCATION } });
    const link = screen.getByRole("link", { name: "checks/sales/orders.yml:11:5" });
    expect(link.getAttribute("href")).toBe("#source");
    expect(link.querySelector("code")?.textContent).toBe("checks/sales/orders.yml:11:5");
  });

  it("the link is there while /source failed: the section is on the page", async () => {
    await renderSource(EMAIL, INTERNAL);
    expect(screen.getByRole("link", { name: detail(EMAIL).source }).getAttribute("href")).toBe("#source");
  });

  it("plain text when the Source section is not on the page", () => {
    render(<Identity check={detail(EMAIL)} sourceLinked={false} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText(detail(EMAIL).source).tagName).toBe("CODE");
  });

  it("no link and no section on the not-found panel", async () => {
    await renderCheck("no-such-check", { check: notFound(), history: notFound() });
    expect(document.querySelector('a[href="#source"]')).toBeNull();
    expect(document.getElementById("source")).toBeNull();
  });
});

// ---- P13 ------------------------------------------------------------------------

describe("P13: what the source does not show", () => {
  it("applies: the filter sentence, as text below the lines, the filter in <code>", async () => {
    await renderSource(AVG, AVG_SOURCE);
    const filter = note("filter");
    expect(text(filter ?? document.body)).toBe("Only rows matching this file's filter: status != 'test' (line 3) are checked.");
    expect(filter?.querySelector("code")?.textContent).toBe("filter: status != 'test'");
    expect(filter?.tagName).toBe("P");
    expect(filter?.closest("pre")).toBeNull();
    expect(block().compareDocumentPosition(filter ?? document.body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("applies: shown whether or not /sql compiled", async () => {
    await renderSource(AVG, AVG_SOURCE, { sql: { ...REMOTE_EVENTS_SQL, check_id: AVG } });
    expect(text(screen.getByRole("region", { name: "SQL" }))).toContain("Cannot compile");
    expect(text(note("filter") ?? document.body)).toBe(
      "Only rows matching this file's filter: status != 'test' (line 3) are checked.",
    );
  });

  it("does not apply, sql_metric ('Custom'): both sentences", async () => {
    await renderSource(CUSTOM, CUSTOM_SOURCE, { check: detailLike(CUSTOM, { name: "Custom", metric: "sql_metric" }) });
    expect(text(note("filter") ?? document.body)).toBe(
      "This file's filter: (line 2) does not apply to this check. Its query runs exactly as written.",
    );
    expect(note("filter")?.querySelector("code")?.textContent).toBe("filter:");
  });

  it("does not apply, schema: the first sentence only", async () => {
    await renderSource(FILTERED_SCHEMA, FILTERED_SCHEMA_SOURCE, { check: detailLike(FILTERED_SCHEMA, { metric: "schema" }) });
    expect(text(note("filter") ?? document.body)).toBe("This file's filter: (line 2) does not apply to this check.");
  });

  it.each([
    ["503", UNAVAILABLE],
    ["network", "network-error" as const],
  ])("does not apply, /checks/{id} %s: the first sentence only (the metric is unknown)", async (_, check) => {
    await renderCheck(CUSTOM, { check, history: ok(page([])), source: ok(CUSTOM_SOURCE), sql: ok({ ...EMAIL_SQL, check_id: CUSTOM }) });
    expect(text(note("filter") ?? document.body)).toBe("This file's filter: (line 2) does not apply to this check.");
  });

  it("no filter: no filter sentence", async () => {
    await renderSource(EMAIL, EMAIL_SOURCE);
    expect(note("filter")).toBeNull();
  });

  it("the defaults sentence on every 200, after the filter sentence", async () => {
    await renderSource(AVG, AVG_SOURCE);
    const defaults = note("defaults");
    expect(text(defaults ?? document.body)).toBe(DEFAULTS_SENTENCE);
    expect(defaults?.querySelector("code")?.textContent).toBe("_defaults.yml");
    expect(
      (note("filter") ?? document.body).compareDocumentPosition(defaults ?? document.body) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("the defaults sentence with no filter", async () => {
    await renderSource(EMAIL, EMAIL_SOURCE);
    expect(text(note("defaults") ?? document.body)).toBe(DEFAULTS_SENTENCE);
  });
});

// ---- P14 ------------------------------------------------------------------------

describe("P14: invisible characters", () => {
  it("lib/invisible.ts marks U+2028 and U+2029 (U+0085 already)", () => {
    expect(isInvisible(0x2028)).toBe(true);
    expect(isInvisible(0x2029)).toBe(true);
    expect(isInvisible(0x85)).toBe(true);
    expect(isInvisible(0x2027)).toBe(false);
  });

  it("U+202E in a comment and U+2028 in a name: marked in place, numbering and count unchanged, text exact", async () => {
    await renderSource(EMAIL, INVISIBLE_SOURCE);
    expect(numbers()).toEqual(["3", "4", "5", "6"]);
    expect(code().textContent).toBe(INVISIBLE_TEXT);
    const line3 = block().querySelector('[data-line="3"]');
    const line6 = block().querySelector('[data-line="6"]');
    expect(Array.from(line3?.querySelectorAll(".invisible-char") ?? []).map((m) => m.getAttribute("data-cp"))).toEqual(["U+202E"]);
    expect(Array.from(line6?.querySelectorAll(".invisible-char") ?? []).map((m) => m.getAttribute("data-cp"))).toEqual(["U+2028"]);
    expect(line6?.querySelector(".invisible-char")?.textContent).toBe("\u2028");
  });

  it("U+200B in the path: marked in the caption", async () => {
    await renderSource(EMAIL, INVISIBLE_SOURCE);
    const marks = Array.from(caption().querySelectorAll("code .invisible-char")).map((m) => m.getAttribute("data-cp"));
    expect(marks).toEqual(["U+200B"]);
    expect(caption().querySelector("code")?.textContent).toBe(INVISIBLE_SOURCE.path);
  });

  it("Copy copies the text byte for byte", async () => {
    await renderSource(EMAIL, INVISIBLE_SOURCE);
    fireEvent.click(within(sourceSection()).getByRole("button", { name: "Copy the source" }));
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(INVISIBLE_TEXT);
    });
  });

  it("a BOM at the start of line 1 is marked, not stripped; ESC in the file name is marked", async () => {
    await renderSource(EMAIL, BOM_SOURCE);
    expect(numbers()).toEqual(["1"]);
    expect(code().textContent).toBe(BOM_SOURCE.text);
    expect(code().textContent?.charCodeAt(0)).toBe(0xfeff);
    expect(block().querySelector(".invisible-char")?.getAttribute("data-cp")).toBe("U+FEFF");
    expect(Array.from(caption().querySelectorAll("code .invisible-char")).map((m) => m.getAttribute("data-cp"))).toEqual(["U+001B"]);
    fireEvent.click(within(sourceSection()).getByRole("button", { name: "Copy the source" }));
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(BOM_SOURCE.text);
    });
  });

  it("the identity panel's file:line:col is marked too", async () => {
    await renderSource(EMAIL, INVISIBLE_SOURCE, { check: { ...detail(EMAIL), source: "checks/sales/orders\u200B.yml:5:5" } });
    const link = document.querySelector('a[href="#source"]');
    expect(link?.querySelector(".invisible-char")?.getAttribute("data-cp")).toBe("U+200B");
    expect(link?.textContent).toBe("checks/sales/orders\u200B.yml:5:5");
  });

  it("CSS keeps a line-breaking character on one line box", () => {
    for (const cp of ["U+2028", "U+2029", "U+0085"]) expect(CSS).toContain(`.invisible-char[data-cp="${cp}"]`);
  });
});

// ---- P15 ------------------------------------------------------------------------

describe("P15: span unavailable", () => {
  it("the line with the path, then the filter sentence, then the defaults sentence; no block, no caption", async () => {
    await renderSource(ONE, UNAVAILABLE_SOURCE);
    expect(sourceSection().querySelector("pre")).toBeNull();
    expect(note("as-loaded")).toBeNull();
    const sentences = Array.from(sourceSection().querySelectorAll(":scope > p")).map(text);
    expect(sentences).toEqual([
      "The lines of this check could not be shown; it is in checks/sales/one.yml.",
      "Only rows matching this file's filter: status != 'test' (line 1) are checked.",
      DEFAULTS_SENTENCE,
    ]);
    expect(note("unavailable")?.querySelector("code")?.textContent).toBe("checks/sales/one.yml");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
  });

  it("no filter: the line and the defaults sentence", async () => {
    await renderSource(ONE, { ...UNAVAILABLE_SOURCE, filter: null });
    expect(Array.from(sourceSection().querySelectorAll(":scope > p")).map(text)).toEqual([
      "The lines of this check could not be shown; it is in checks/sales/one.yml.",
      DEFAULTS_SENTENCE,
    ]);
  });

  it("the path is marked (P14)", async () => {
    await renderSource(ONE, { ...UNAVAILABLE_SOURCE, path: "checks/sales/o\u200Bne.yml" });
    expect(note("unavailable")?.querySelector(".invisible-char")?.getAttribute("data-cp")).toBe("U+200B");
  });
});

// ---- P16 ------------------------------------------------------------------------

describe("P16: long lines (the 360 px run is by hand)", () => {
  const LONG = `      valid_regex: '${"[a-z0-9]".repeat(24)}'`;

  it("the block is a focusable, labelled region with the no-wrap modifier", async () => {
    await renderSource(EMAIL, { ...EMAIL_SOURCE, text: `  - invalid_count(email) = 0:\n${LONG}`, start_line: 10, end_line: 11 });
    expect(LONG.length).toBeGreaterThanOrEqual(200);
    const pre = block();
    expect(pre.getAttribute("role")).toBe("region");
    expect(pre.tabIndex).toBe(0);
    expect(pre.classList.contains("code-block")).toBe(true);
    expect(pre.classList.contains("code-block--lines")).toBe(true);
    expect(screen.getByRole("region", { name: "The check's lines" })).toBe(pre);
    expect(sourceSection().classList.contains("source")).toBe(true);
  });

  /** The declarations of the first rule whose selector list is exactly `selector`. */
  function rule(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const match = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(CSS);
    if (match === null) throw new Error(`no rule ${selector}`);
    return match[1] ?? "";
  }

  it("CSS: no wrapping, sideways scroll inside the block, min-width: 0 down the chain", () => {
    expect(rule(".code-block--lines")).toMatch(/white-space:\s*pre;/);
    expect(rule(".code-block--lines")).toMatch(/overflow-wrap:\s*normal;/);
    expect(rule(".code-block")).toMatch(/overflow-x:\s*auto;/);
    expect(rule(".code-block")).toMatch(/min-width:\s*0;/);
    expect(rule(".code-block")).toMatch(/max-width:\s*100%;/);
    expect(rule(".source")).toMatch(/min-width:\s*0;/);
  });

  it("CSS: numbers are generated from data-line and cannot be selected", () => {
    const numbersRule = rule(".code-block--lines .line::before");
    expect(numbersRule).toMatch(/content:\s*attr\(data-line\);/);
    expect(numbersRule).toMatch(/user-select:\s*none;/);
    expect(numbersRule).toMatch(/var\(--line-digits/);
  });
});
