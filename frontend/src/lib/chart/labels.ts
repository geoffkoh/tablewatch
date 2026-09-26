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

export interface Wanted {
  id: string;
  /** The label's desired centre. */
  y: number;
}

/**
 * Vertical positions for a column of labels, each as close to its wanted
 * centre as possible, none overlapping (`gap` apart, centre to centre), all
 * inside [top, bottom] when they fit. Pure; returns centres by id.
 */
export function stackLabels(items: readonly Wanted[], gap: number, top: number, bottom: number): Map<string, number> {
  const sorted = [...items].sort((a, b) => a.y - b.y || a.id.localeCompare(b.id));
  const ys = sorted.map((i) => Math.min(Math.max(i.y, top), bottom));
  for (let i = 1; i < ys.length; i += 1) {
    const prev = ys[i - 1] ?? top;
    if ((ys[i] ?? 0) < prev + gap) ys[i] = prev + gap;
  }
  const last = ys.length - 1;
  if (last >= 0 && (ys[last] ?? 0) > bottom) {
    ys[last] = bottom;
    for (let i = last - 1; i >= 0; i -= 1) {
      const next = ys[i + 1] ?? bottom;
      if ((ys[i] ?? 0) > next - gap) ys[i] = next - gap;
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
