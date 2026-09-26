/**
 * WCAG AA contrast for the palette in both colour schemes (O11). The tokens
 * are parsed from the real stylesheet, so the test checks what ships.
 */
import { describe, expect, it } from "vitest";
import tokensCss from "../styles/tokens.css?raw";

type Palette = Record<string, string>;

function parseBlock(block: string): Palette {
  const palette: Palette = {};
  for (const match of block.matchAll(/--tw-([a-z-]+):\s*(#[0-9a-f]{6})\s*;/gi)) {
    const [, name, value] = match;
    if (name !== undefined && value !== undefined) palette[name] = value.toLowerCase();
  }
  return palette;
}

function palettes(): { light: Palette; dark: Palette } {
  const darkStart = tokensCss.indexOf("@media (prefers-color-scheme: dark)");
  if (darkStart < 0) throw new Error("no dark scheme in tokens.css");
  const light = parseBlock(tokensCss.slice(0, darkStart));
  const dark = { ...light, ...parseBlock(tokensCss.slice(darkStart)) };
  return { light, dark };
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const STATUSES = ["fail", "error", "warn", "none", "skipped", "pass"] as const;
const MARKS = ["pass", "warn", "fail", "error"] as const;
const TEXT = 4.5; // WCAG 1.4.3, normal text
const NON_TEXT = 3; // WCAG 1.4.11, icons and focus indicators

function pairs(): [string, string, string, number][] {
  const list: [string, string, string, number][] = [];
  const add = (fg: string, bg: string, min: number): void => {
    list.push([`${fg} on ${bg}`, fg, bg, min]);
  };
  for (const bg of ["bg", "surface"]) {
    add("text", bg, TEXT);
    add("text-muted", bg, TEXT);
    add("link", bg, TEXT);
    add("focus", bg, NON_TEXT);
    for (const s of STATUSES) add(`${s}-fg`, bg, TEXT);
  }
  add("bg", "text", TEXT); // the focus tooltip
  for (const s of STATUSES) {
    add(`${s}-fg`, `${s}-tint`, TEXT); // badge label and icon
    add("on-status", `${s}-fg`, NON_TEXT); // the mark inside a filled icon
    add("text", `${s}-tint`, TEXT); // banner text on its tint
  }
  add("text-muted", "error-tint", TEXT);
  add("link", "error-tint", TEXT);
  // Spec 004 D11: the history chart plots on --tw-bg. Marks, boundary lines
  // (band edges), the value line and hairline markers need 3:1; axis and
  // label text 4.5:1 (text and text-muted on bg, above).
  for (const m of MARKS) {
    add(`${m}-mark`, "bg", NON_TEXT);
    add("on-status", `${m}-mark`, NON_TEXT); // the glyph inside a filled mark
  }
  add("series", "bg", NON_TEXT);
  add("skipped-fg", "bg", NON_TEXT); // the skipped mark
  add("text-muted", "bg", NON_TEXT); // rule-change marker, streak bracket, crosshair
  return list;
}

describe.each(["light", "dark"] as const)("the %s palette", (scheme) => {
  const palette = palettes()[scheme];

  it.each(pairs())("%s meets AA", (_, fg, bg, min) => {
    const a = palette[fg];
    const b = palette[bg];
    expect(a, `--tw-${fg}`).toBeDefined();
    expect(b, `--tw-${bg}`).toBeDefined();
    expect(contrast(a ?? "", b ?? "")).toBeGreaterThanOrEqual(min);
  });

  it("gives fail, error and warn different hues", () => {
    const hue = (hex: string): number => {
      const n = Number.parseInt(hex.slice(1), 16);
      const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255) as [number, number, number];
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      if (max === min) return 0;
      const d = max - min;
      const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
      return (h * 60 + 360) % 360;
    };
    const distance = (a: number, b: number): number => Math.min(Math.abs(a - b), 360 - Math.abs(a - b));
    const [fail, error, warn] = (["fail", "error", "warn"] as const).map((s) => hue(palette[`${s}-fg`] ?? "#000000")) as [
      number,
      number,
      number,
    ];
    expect(distance(fail, error)).toBeGreaterThanOrEqual(60);
    expect(distance(fail, warn)).toBeGreaterThanOrEqual(25);
    expect(distance(error, warn)).toBeGreaterThanOrEqual(60);
  });
});

describe("the chart's mark tokens", () => {
  it("are chart-only: separate from the status text tokens, and never used for text", async () => {
    const { default: appCss } = await import("../styles/app.css?raw");
    for (const scheme of ["light", "dark"] as const) {
      const p = palettes()[scheme];
      for (const m of MARKS) expect(p[`${m}-mark`], `${scheme} --tw-${m}-mark`).toMatch(/^#[0-9a-f]{6}$/);
      expect(p.series).toBeDefined();
      expect(p.grid).toBeDefined();
    }
    // Text never wears a mark colour (dataviz): no `color:` or text `fill` rule uses one,
    // apart from the marks themselves (.mark--*), whose colour fills the shape.
    const offending = appCss
      .split("}")
      .filter((rule) => /-mark\)/.test(rule) && /(^|[\s;{])color:/.test(rule) && !/\.mark--/.test(rule));
    expect(offending).toEqual([]);
  });
});

describe("the contrast function", () => {
  it("matches the WCAG reference values", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });
});
