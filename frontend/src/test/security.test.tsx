/**
 * X4 (data renders as text) and the source rules that keep the bundle inside
 * its CSP: no HTML injection APIs, no eval, no inline styles, no web storage,
 * no request outside the one client.
 */
import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mapLatest } from "./fixtures/derived";
import { recorded, RUN_ID, STARTED } from "./fixtures/states";
import { CLOCK, renderOverview, rowFor, setClock, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("X4: data values render as text", () => {
  const NAME = "<img src=x onerror=alert(1)>";
  const MESSAGE = "<script>alert(1)</script>";

  const hostile = (() => {
    const fixture = mapLatest(recorded, (c) => c.latest);
    const base = fixture.checks.items[0];
    if (base === undefined) throw new Error("fixture has no checks");
    fixture.checks.items.push({
      ...base,
      id: "0123456789abcdef",
      name: NAME,
      expression: "row_count > 0",
      latest: {
        run_id: RUN_ID.B,
        started_at: STARTED.B,
        since: STARTED.B,
        trigger: "cli",
        outcome: "error",
        value: null,
        display_value: "—",
        message: MESSAGE,
        last_evaluated: null,
      },
    });
    fixture.checks.total += 1;
    fixture.project.counts.checks += 1;
    fixture.project.name = "<b>retail</b>";
    fixture.project.ok = false;
    fixture.project.diagnostics = [
      { severity: "error", message: "<iframe src=//evil.example>", location: { file: "<svg onload=alert(1)>.yml", line: 1, column: 1 } },
    ];
    return fixture;
  })();

  it("creates no element from a check name, a message, a project name or a diagnostic", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    const { container } = await renderOverview(hostile);
    const row = rowFor("0123456789abcdef");
    expect(text(row)).toContain(NAME);
    expect(text(row)).toContain(MESSAGE);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("<b>retail</b>");
    expect(text(document.body)).toContain("<iframe src=//evil.example>");
    expect(text(document.body)).toContain("<svg onload=alert(1)>.yml:1:1");
    expect(document.querySelectorAll("img, script, iframe, b")).toHaveLength(0);
    expect(container.querySelectorAll("svg[onload], [onerror]")).toHaveLength(0);
    expect(alert).not.toHaveBeenCalled();
  });
});

/** Every source file under src/, as text. */
const SOURCES = import.meta.glob<string>("../**/*.{ts,tsx,css}", {
  query: "?raw",
  import: "default",
  eager: true,
});

// Built from parts so this file does not match its own patterns.
const j = (...parts: string[]): string => parts.join("");

function offenders(pattern: RegExp, files: Record<string, string> = SOURCES): string[] {
  return Object.entries(files)
    .filter(([, source]) => pattern.test(source))
    .map(([path]) => path);
}

describe("source rules", () => {
  it("reads the sources it checks", () => {
    const paths = Object.keys(SOURCES);
    expect(paths).toContain("../api/api.ts");
    expect(paths).toContain("../pages/Overview.tsx");
    expect(paths.length).toBeGreaterThan(15);
  });

  it.each([
    j("inner", "HTML"),
    j("outer", "HTML"),
    j("insertAdjacent", "HTML"),
    j("dangerously", "SetInnerHTML"),
    j("document", "\\.write"),
    j("\\beval", "\\s*\\("),
    j("new\\s+", "Function\\b"),
    j("src", "doc"),
    j("createContextual", "Fragment"),
  ])("never uses %s", (pattern) => {
    expect(offenders(new RegExp(pattern))).toEqual([]);
  });

  it("sets no inline style: no style prop, no style attribute, no style element", () => {
    const tsx = Object.fromEntries(Object.entries(SOURCES).filter(([p]) => p.endsWith(".tsx")));
    expect(offenders(new RegExp(j("\\bstyle", "\\s*=")), tsx)).toEqual([]);
    expect(offenders(new RegExp(j("<", "style\\b")), tsx)).toEqual([]);
    expect(offenders(new RegExp(j("\\.style", "\\b")), tsx)).toEqual([]);
  });

  it("keeps no API data in web storage and registers no service worker", () => {
    for (const api of [j("local", "Storage"), j("session", "Storage"), j("indexed", "DB"), j("service", "Worker")]) {
      expect(offenders(new RegExp(api)), api).toEqual([]);
    }
  });

  it("calls fetch only from the one client", () => {
    const callers = offenders(new RegExp(j("\\bfetch", "\\s*\\("))).filter((p) => !p.startsWith("./"));
    expect(callers).toEqual(["../api/api.ts"]);
  });

  it("reads nothing from the build environment but MODE and PROD", () => {
    const env = new RegExp(j("import\\.meta\\.", "env\\.(?!MODE\\b|PROD\\b)"));
    expect(offenders(env)).toEqual([]);
  });

  it("names no third-party origin to load from", () => {
    const app = Object.fromEntries(Object.entries(SOURCES).filter(([p]) => !p.startsWith("./")));
    expect(offenders(new RegExp(j("https?:", "//")), app)).toEqual([]);
    expect(offenders(new RegExp(j("@", "import")), app)).toEqual([]);
  });
});
