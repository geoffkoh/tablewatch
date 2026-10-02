/**
 * Client routes, without a router (spec 004, decision 7). Links are plain
 * `<a href>` and every navigation is a full page load: the server answers
 * every client path with index.html (spec 003, W3).
 *
 * `/checks` and `/checks/` are the check explorer (spec 015); its query
 * (`?q=…&status=…`) is read by the page, not here.
 *
 * A check path is `/checks/<id>` or `/checks/<id>/`, with exactly one
 * non-empty segment. The segment is decoded once, inside try/catch, and must
 * match the loader's id pattern (`config/loader.py` `ID_PATTERN`, at most 64
 * characters). Anything else is "page not found", and no request is made for
 * it: `..`, `%2e%2e`, `a%2Fb`, `a%3Fb`, a malformed `%`, 65 characters.
 */

/** The loader's id pattern and the store's column width. */
export const CHECK_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;
export const MAX_CHECK_ID_LENGTH = 64;

export type Route =
  | { page: "overview" }
  | { page: "explorer" }
  | { page: "check"; id: string }
  | { page: "not-found" };

/** True for a string the server could hold as a check id. */
export function isCheckId(id: string): boolean {
  return id.length > 0 && id.length <= MAX_CHECK_ID_LENGTH && CHECK_ID_PATTERN.test(id);
}

/** Which page a path is. Pure: the path comes from `location.pathname`. */
export function parseRoute(path: string): Route {
  if (path === "/" || path === "/index.html") return { page: "overview" };
  if (path === "/checks" || path === "/checks/") return { page: "explorer" };
  const match = /^\/checks\/([^/]+)\/?$/.exec(path);
  if (match === null) return { page: "not-found" };
  const raw = match[1] ?? "";
  let id: string;
  try {
    id = decodeURIComponent(raw);
  } catch {
    return { page: "not-found" };
  }
  return isCheckId(id) ? { page: "check", id } : { page: "not-found" };
}

/** The link to a check's page. */
export function checkHref(id: string): string {
  return `/checks/${encodeURIComponent(id)}`;
}

/** The check explorer, with nothing filtered. */
export const EXPLORER_HREF = "/checks";
