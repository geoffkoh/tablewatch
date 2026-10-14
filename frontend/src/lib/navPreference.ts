/**
 * Whether the side navigation is collapsed to an icon rail, remembered per
 * browser (spec 039, P-D5). This is the only module that touches web
 * storage: `test/security.test.tsx` scans every other file for it. Storage
 * may throw (private browsing, a full quota) or be entirely absent, so every
 * call is inside try/catch; the default, and any failure, is expanded. No
 * API data is ever stored here — only this one layout preference.
 */
const KEY = "tablewatch.nav";
const RAIL = "rail";

/** True when the rail was chosen on a previous visit. Never throws. */
export function readNavCollapsed(): boolean {
  try {
    return window.localStorage.getItem(KEY) === RAIL;
  } catch {
    return false;
  }
}

/** Remembers the choice, or silently does nothing if storage is unavailable. */
export function writeNavCollapsed(collapsed: boolean): void {
  try {
    if (collapsed) window.localStorage.setItem(KEY, RAIL);
    else window.localStorage.removeItem(KEY);
  } catch {
    // Storage may be unavailable or full; the preference just does not persist.
  }
}
