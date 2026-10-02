/**
 * Spec 005, adversarial: the SQL section on answers the acceptance tests do
 * not use (edges of P1, P7, P9, P14, P15).
 */
import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckDetail, CheckSql, Statement } from "../api/types";
import { isInvisible, segments } from "../lib/invisible";
import { detailOf, recordedHistory } from "./fixtures/detail";
import { EMAIL_SQL, SCHEMA_SQL, VOLUME_SQL } from "./fixtures/sql";
import { recorded } from "./fixtures/states";
import { CLOCK, checkUrls, ok, renderCheck, setClock, stubCheckServer, text, type Answer } from "./render";

const EMAIL = "b1ceb8262d8b5441";

const writeText = vi.fn<(text: string) => Promise<void>>();

function setContext(secure: boolean, clipboard: boolean): void {
  Object.defineProperty(window, "isSecureContext", { value: secure, configurable: true });
  Object.defineProperty(navigator, "clipboard", { value: clipboard ? { writeText } : undefined, configurable: true });
}

beforeEach(() => {
  setClock(CLOCK);
  writeText.mockReset();
  writeText.mockResolvedValue(undefined);
  setContext(true, true);
});

afterEach(() => {
  vi.useRealTimers();
});

function sqlSection(): HTMLElement {
  return screen.getByRole("region", { name: "SQL" });
}

function detail(id: string): CheckDetail {
  return detailOf(recorded, id);
}

async function renderSql(sql: CheckSql | Answer): Promise<void> {
  const answer: Answer = typeof sql === "object" && "check_id" in sql ? ok(sql) : (sql as Answer);
  await renderCheck(EMAIL, { check: ok(detail(EMAIL)), history: ok(recordedHistory(EMAIL)), sql: answer });
}

const UNKNOWN: Statement = { kind: "failed_rows", sql: "SELECT * FROM t" } as unknown as Statement;

describe("P15 edges: only statements of an unknown kind", () => {
  it("does not leave the section empty under its heading", async () => {
    await renderSql({ ...EMAIL_SQL, statements: [UNKNOWN] });
    const words = Array.from(sqlSection().children)
      .slice(1)
      .map(text)
      .join(" ")
      .trim();
    expect(words).toBe("This check sends no statement of its own.");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("an unknown kind next to a schema lookup still says it reads no rows", async () => {
    await renderSql({ ...SCHEMA_SQL, check_id: EMAIL, statements: [UNKNOWN] });
    expect(text(sqlSection())).toContain("It reads no rows, so it has no SQL.");
    expect(sqlSection().querySelectorAll("pre")).toHaveLength(0);
  });
});

describe("P1 edges: singular counts", () => {
  it("a scan shared with exactly one other check says '1 other'", async () => {
    const scan = VOLUME_SQL.statements[0];
    if (scan?.kind !== "scan") throw new Error("fixture");
    await renderSql({ ...VOLUME_SQL, check_id: EMAIL, statements: [{ ...scan, measures: 1, shared_by: 1 }] });
    expect(text(sqlSection())).toContain("That one read computes 1 value, used by this check and 1 other.");
  });

  it("a query shared with one other check says '1 other check uses'", async () => {
    await renderSql({
      ...EMAIL_SQL,
      statements: [{ kind: "query", sql: "SELECT 1", shared_by: 1 }],
    });
    expect(text(sqlSection())).toContain("1 other check uses the same statement.");
  });
});

describe("P8 edges: the sentence around the block is text too", () => {
  it("a hostile dataset and datasource name render literally", async () => {
    const hostile = "<img src=x onerror=alert(1)>";
    await renderSql({ ...EMAIL_SQL, dataset: hostile, datasource: hostile, dialect: hostile });
    expect(text(sqlSection())).toContain(`When tablewatch checks ${hostile} on ${hostile} (${hostile})`);
    expect(document.querySelectorAll("img, [onerror]")).toHaveLength(0);
  });
});

describe("P9 edges: when copying is possible", () => {
  it("a clipboard in a context that is not secure is not used: 'Select all' instead", async () => {
    setContext(false, true);
    await renderSql(EMAIL_SQL);
    expect(within(sqlSection()).queryByRole("button", { name: /^Copy/ })).toBeNull();
    expect(within(sqlSection()).getByRole("button", { name: "Select all of the scan" })).toBeTruthy();
  });

  it("a secure context without a clipboard: 'Select all' instead", async () => {
    setContext(true, false);
    await renderSql(EMAIL_SQL);
    expect(within(sqlSection()).queryByRole("button", { name: /^Copy/ })).toBeNull();
  });

  it("each statement copies its own text", async () => {
    await renderSql({
      ...EMAIL_SQL,
      statements: [
        ...EMAIL_SQL.statements,
        { kind: "query", sql: "SELECT 2", shared_by: 0 },
        { kind: "query", sql: "SELECT 3", shared_by: 0 },
      ],
    });
    const buttons = within(sqlSection()).getAllByRole("button", { name: "Copy the query" });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1] as HTMLElement);
    await vi.waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("SELECT 3;");
    });
  });
});

describe("P7 edges: late answers", () => {
  it("a late /sql failure after a Refresh that succeeded does not replace the SQL", async () => {
    let reject: (e: Error) => void = () => undefined;
    const slow = new Promise<Response>((_, r) => {
      reject = r;
    });
    await renderSql(EMAIL_SQL);
    const urls = checkUrls(EMAIL);
    const base = globalThis.fetch as unknown as (input: RequestInfo | URL) => Promise<Response>;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => (String(input) === urls.sql ? slow : base(input))));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    stubCheckServer(EMAIL, { check: ok(detail(EMAIL)), history: ok(recordedHistory(EMAIL)), sql: ok(EMAIL_SQL) });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    await act(async () => {
      reject(new TypeError("Failed to fetch"));
      await slow.catch(() => undefined);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(sqlSection().querySelectorAll("pre")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
  });
});

describe("P14 edges: every listed range is marked, and nothing else", () => {
  const marked = [
    0x00, 0x01, 0x0b, 0x0d, 0x1b, 0x1f, 0x7f, 0x80, 0x9f, 0xad, 0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x202a,
    0x202b, 0x202c, 0x202d, 0x202e, 0x2028, 0x2029, 0x2060, 0x2064, 0x2066, 0x2067, 0x2068, 0x2069, 0xfeff,
  ];
  const plain = [0x09, 0x0a, 0x20, 0x41, 0xa0, 0xe9, 0x2010, 0x2027, 0x205f, 0x206a, 0xfefe, 0x1f600];

  it.each(marked)("U+%s is marked", (cp) => {
    expect(isInvisible(cp)).toBe(true);
  });

  it.each(plain)("U+%s is not marked", (cp) => {
    expect(isInvisible(cp)).toBe(false);
  });

  it("segments join back to the exact text, astral characters included", () => {
    const sample = "a‮b\u{1f600}​\u0000c\r\n\td﻿";
    expect(
      segments(sample)
        .map((s) => s.text)
        .join(""),
    ).toBe(sample);
  });
});
