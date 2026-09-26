import type { ReactElement } from "react";
import type { Status } from "../lib/status";

/**
 * One distinct shape per status, so status survives greyscale and colour
 * blindness: pass a circle with a tick, fail an octagon with a cross, warn a
 * triangle with "!", error a square with "?", no result a dashed empty
 * circle, skipped a circle with a skip arrow.
 *
 * Drawn in a 16 x 16 box centred on (8, 8). The status icons and the history
 * chart's marks both draw these (spec 004, decision 9), so a mark and the
 * icon for the same status cannot drift apart.
 */
export const SHAPES: Readonly<Record<Status, ReactElement>> = {
  pass: (
    <>
      <circle cx="8" cy="8" r="7" className="icon-fill" />
      <path d="M4.5 8.3 7 10.7l4.6-5" className="icon-mark" />
    </>
  ),
  fail: (
    <>
      <path d="M5.1 1h5.8L15 5.1v5.8L10.9 15H5.1L1 10.9V5.1Z" className="icon-fill" />
      <path d="m5.5 5.5 5 5m0-5-5 5" className="icon-mark" />
    </>
  ),
  warn: (
    <>
      <path d="M8 1.2 15.2 14H.8Z" className="icon-fill" />
      <path d="M8 5.8v4" className="icon-mark" />
      <circle cx="8" cy="12" r="0.9" className="icon-dot" />
    </>
  ),
  error: (
    <>
      <rect x="1.5" y="1.5" width="13" height="13" rx="2" className="icon-fill" />
      <path d="M6 6.2a2 2 0 1 1 2.8 1.8c-.5.2-.8.6-.8 1.1v.6" className="icon-mark" />
      <circle cx="8" cy="11.8" r="0.9" className="icon-dot" />
    </>
  ),
  none: (
    <>
      <circle cx="8" cy="8" r="6.2" className="icon-outline icon-dashed" />
      <path d="M5.5 8h5" className="icon-mark icon-mark--plain" />
    </>
  ),
  skipped: (
    <>
      <circle cx="8" cy="8" r="6.2" className="icon-outline" />
      <path d="m5.5 5.5 2.5 2.5-2.5 2.5m3-5 2.5 2.5-2.5 2.5" className="icon-mark icon-mark--plain" />
    </>
  ),
};


/** The shape for a status, in its 16 x 16 box. */
export function StatusShape({ status }: { status: Status }): ReactElement {
  return SHAPES[status];
}
