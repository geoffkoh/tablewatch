/**
 * Label placement without measuring the DOM (chart requirement 6). Widths
 * are estimated from the character count at the chart's font size, which is
 * generous for the system sans, so an estimate errs towards more space.
 */

/** Average advance of one character at the chart's 12-unit font, rounded up. */
export const CHAR_WIDTH = 7;
/** A line of chart text, with leading. */
export const LINE_HEIGHT = 14;

export function textWidth(text: string, charWidth = CHAR_WIDTH): number {
  return Array.from(text).length * charWidth;
}

/** Centre to centre, between the latest value's label and any other (spec 012 B7). */
export const LATEST_GAP = 20;

export interface Wanted {
  id: string;
  /** The label's desired centre. */
  y: number;
  /**
   * Where the label goes in the column's order, before its `y` is considered:
   * -1 always first (top), 1 always last (bottom), 0 (the default) by `y`.
   * An off-range edge label names a side, so it stays on that side (B7).
   */
  rank?: -1 | 0 | 1;
  /** Breaks a tie in `y` before the id does: smaller first (higher up). */
  order?: number;
}

/** The distance two neighbouring labels keep, centre to centre. */
export type Gap = number | ((upper: Wanted, lower: Wanted) => number);

/**
 * Vertical positions for a column of labels, each as close to its wanted
 * centre as possible, none overlapping (`gap` apart, centre to centre, or as
 * `gap` says for each neighbouring pair), all inside [top, bottom] when they
 * fit. Order is by `rank`, then wanted centre, then `order`, then id. Pure; returns centres
 * by id.
 */
export function stackLabels(items: readonly Wanted[], gap: Gap, top: number, bottom: number): Map<string, number> {
  const gapOf = typeof gap === "number" ? (): number => gap : gap;
  const sorted = [...items].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0) || a.y - b.y || (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id));
  const ys = sorted.map((i) => Math.min(Math.max(i.y, top), bottom));
  const between = (i: number): number => {
    const upper = sorted[i - 1];
    const lower = sorted[i];
    return upper === undefined || lower === undefined ? 0 : gapOf(upper, lower);
  };
  for (let i = 1; i < ys.length; i += 1) {
    const prev = ys[i - 1] ?? top;
    if ((ys[i] ?? 0) < prev + between(i)) ys[i] = prev + between(i);
  }
  const last = ys.length - 1;
  if (last >= 0 && (ys[last] ?? 0) > bottom) {
    ys[last] = bottom;
    for (let i = last - 1; i >= 0; i -= 1) {
      const next = ys[i + 1] ?? bottom;
      if ((ys[i] ?? 0) > next - between(i + 1)) ys[i] = next - between(i + 1);
    }
  }
  const out = new Map<string, number>();
  sorted.forEach((item, i) => out.set(item.id, ys[i] ?? item.y));
  return out;
}

export interface Span {
  id: string;
  x0: number;
  x1: number;
}

/**
 * Rows for horizontal labels (rule-change markers): each label takes the
 * first row where it does not overlap a label already placed. Pure.
 */
export function assignRows(spans: readonly Span[], padding = 6): Map<string, number> {
  const rows: number[] = []; // the right edge of the last label in each row
  const out = new Map<string, number>();
  for (const s of [...spans].sort((a, b) => a.x0 - b.x0)) {
    let row = rows.findIndex((right) => s.x0 >= right + padding);
    if (row < 0) {
      row = rows.length;
      rows.push(s.x1);
    } else {
      rows[row] = s.x1;
    }
    out.set(s.id, row);
  }
  return out;
}

/** Cut text to a character budget, with an ellipsis. */
export function truncate(text: string, max: number): string {
  const chars = Array.from(text);
  return chars.length <= max ? text : `${chars.slice(0, Math.max(1, max - 1)).join("")}…`;
}
