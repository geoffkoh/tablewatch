/**
 * The check explorer's pure parts (specs 015, 016): the query it keeps in the
 * URL, the search, the status, tag, owner and datasource filters with their
 * counts, the `checks/` tree, and the counts on every folder and file. No
 * React and no DOM here, so each rule is tested alone.
 */
import type { CheckSummary } from "../api/types";
import { countStatuses, STATUS_ORDER, statusOf, type Status, type StatusCounts } from "./status";

/** The longest search, and the longest filter value, kept from a URL or the box (E12, F12). */
export const MAX_QUERY_LENGTH = 200;

/** The filters beside Status (spec 016), in their order on the page and in the URL. */
export type FacetKey = "tag" | "owner" | "datasource";
export const FACET_KEYS: readonly FacetKey[] = ["tag", "owner", "datasource"];

/**
 * What the explorer shows: a search text, the selected statuses, and the
 * selected tag, owner and datasource values. None selected in a filter means
 * all. The empty value `""` stands for "No tags", "No owner", "No datasource"
 * (decision 1).
 */
export interface ExplorerQuery {
  q: string;
  statuses: Status[];
  tag: string[];
  owner: string[];
  datasource: string[];
}

/** Nothing searched, nothing filtered. */
export const EMPTY_QUERY: ExplorerQuery = { q: "", statuses: [], tag: [], owner: [], datasource: [] };

/** The fieldset legend of each filter. */
export const FACET_LEGENDS: Readonly<Record<FacetKey, string>> = {
  tag: "Tag",
  owner: "Owner",
  datasource: "Datasource",
};

/** The label of the empty value (F7, F8). */
export const NONE_LABELS: Readonly<Record<FacetKey, string>> = {
  tag: "No tags",
  owner: "No owner",
  datasource: "No datasource",
};

function isStatus(value: string): value is Status {
  return (STATUS_ORDER as readonly string[]).includes(value);
}

/** Selected statuses, deduplicated, in problem-first order. */
export function orderStatuses(statuses: Iterable<Status>): Status[] {
  const chosen = new Set(statuses);
  return STATUS_ORDER.filter((s) => chosen.has(s));
}

/** Text cut to its limit by code point, so an emoji is never split in half. */
export function cutQuery(q: string): string {
  return Array.from(q).slice(0, MAX_QUERY_LENGTH).join("");
}

/** Names compare without case first, then exactly, so the order is the same everywhere. */
function byName(a: string, b: string): number {
  const la = a.toLowerCase();
  const lb = b.toLowerCase();
  if (la !== lb) return la < lb ? -1 : 1;
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

/** Values by name, the empty ("none") value last (F2). */
export function compareValues(a: string, b: string): number {
  if (a === "" || b === "") return a === b ? 0 : a === "" ? 1 : -1;
  return byName(a, b);
}

/** Filter values cut to 200 code points, deduplicated, in the URL's normal order (F12). */
export function orderValues(values: Iterable<string>): string[] {
  return [...new Set(Array.from(values, cutQuery))].sort(compareValues);
}

/**
 * The query from `location.search`. Unknown statuses are ignored; `q` and
 * every filter value are cut to 200 code points (E12, F12). Unknown filter
 * values are kept: a stale link explains itself (F11, decision 2).
 */
export function parseExplorerQuery(search: string): ExplorerQuery {
  const params = new URLSearchParams(search);
  return {
    q: cutQuery(params.get("q") ?? ""),
    statuses: orderStatuses(params.getAll("status").filter(isStatus)),
    tag: orderValues(params.getAll("tag")),
    owner: orderValues(params.getAll("owner")),
    datasource: orderValues(params.getAll("datasource")),
  };
}

/**
 * The query as a `location.search` string, parameters in the order `q`,
 * `status`, `tag`, `owner`, `datasource` (F10), or "" for everything. A
 * search of only spaces is no search.
 */
export function explorerSearch(query: ExplorerQuery): string {
  const params = new URLSearchParams();
  if (query.q.trim() !== "") params.set("q", cutQuery(query.q));
  for (const status of orderStatuses(query.statuses)) params.append("status", status);
  for (const key of FACET_KEYS) for (const value of orderValues(query[key])) params.append(key, value);
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

/** True when the query narrows anything (F14). */
export function isFiltering(query: ExplorerQuery): boolean {
  return query.q.trim() !== "" || query.statuses.length > 0 || FACET_KEYS.some((key) => query[key].length > 0);
}

/**
 * A check's values for a filter; `""` is "none". A check's tags are its
 * dataset's. `not_a_name` and `none` datasources are both served as `""`
 * (decision 4).
 */
export function valuesOf(check: CheckSummary, key: FacetKey): readonly string[] {
  switch (key) {
    case "tag":
      return check.tags.length === 0 ? [""] : check.tags;
    case "owner":
      return [check.owner ?? ""];
    case "datasource":
      return [check.datasource];
  }
}

/**
 * Case-insensitive substring of name, expression, dataset, file path, id,
 * a tag, the owner or the datasource; leading and trailing spaces ignored
 * (E8, F13).
 */
export function matchesText(check: CheckSummary, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (needle === "") return true;
  const fields = [check.name, check.expression, check.dataset, check.location.file, check.id, check.datasource];
  if (check.owner !== null) fields.push(check.owner);
  return [...fields, ...check.tags].some((field) => field.toLowerCase().includes(needle));
}

/**
 * The search and every filter together (E10, F5: AND across filters, OR
 * within one). `except` leaves one filter out, for that filter's counts (F6).
 */
export function filterChecks(
  checks: readonly CheckSummary[],
  query: ExplorerQuery,
  except: FacetKey | "status" | null = null,
): CheckSummary[] {
  const statuses = except === "status" ? new Set<Status>() : new Set(query.statuses);
  const facets = FACET_KEYS.filter((key) => key !== except && query[key].length > 0).map(
    (key) => [key, new Set(query[key])] as const,
  );
  return checks.filter(
    (c) =>
      matchesText(c, query.q) &&
      (statuses.size === 0 || statuses.has(statusOf(c))) &&
      facets.every(([key, chosen]) => valuesOf(c, key).some((v) => chosen.has(v))),
  );
}

/** One checkbox of a filter. */
export interface FacetOption {
  value: string;
  /** What the checkbox reads before its count: the value as written, or its "none" label. */
  label: string;
  /** "(not defined)" for a datasource the project does not define (F8); null otherwise. */
  note: string | null;
  /** Checks matching the search and every other filter that have this value (F6). */
  count: number;
  checked: boolean;
}

/**
 * The options of one filter: every value some loaded check has, and every
 * selected one (F11), with counts over the checks that match the search and
 * every **other** filter (F6), sorted by name with "none" last (F2).
 */
export function facetOptions(checks: readonly CheckSummary[], query: ExplorerQuery, key: FacetKey): FacetOption[] {
  const notDefined = new Set<string>();
  const present = new Set<string>();
  for (const check of checks) {
    for (const value of valuesOf(check, key)) present.add(value);
    if (key === "datasource" && check.datasource_state === "not_defined") notDefined.add(check.datasource);
  }
  const counts = new Map<string, number>();
  for (const check of filterChecks(checks, query, key)) {
    for (const value of new Set(valuesOf(check, key))) counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  const selected = new Set(query[key]);
  return orderValues([...present, ...selected]).map((value) => ({
    value,
    label: value === "" ? NONE_LABELS[key] : value,
    note: value !== "" && notDefined.has(value) ? "(not defined)" : null,
    count: counts.get(value) ?? 0,
    checked: selected.has(value),
  }));
}

/**
 * Whether a filter's fieldset is shown: when it offers a choice, or when the
 * URL selects a value (F1, F9, decision 3).
 */
export function showFacet(options: readonly FacetOption[]): boolean {
  return options.length > 1 || options.some((o) => o.checked);
}

/** How many values a long filter shows before "Show all" (F15). */
export const FACET_LIMIT = 10;

/**
 * The options a collapsed filter shows: the 10 with the highest counts (ties
 * by name), plus every ticked one, kept in the list's name order (F15).
 */
export function collapsedOptions(options: readonly FacetOption[], limit = FACET_LIMIT): FacetOption[] {
  if (options.length <= limit) return [...options];
  const top = new Set(
    [...options]
      .sort((a, b) => b.count - a.count || compareValues(a.value, b.value))
      .slice(0, limit)
      .map((o) => o.value),
  );
  return options.filter((o) => o.checked || top.has(o.value));
}

// ---- the tree -----------------------------------------------------------------

export interface FileNode {
  kind: "file";
  /** The file's name, its last path segment. */
  name: string;
  /** The full path as the API sent it. */
  path: string;
  /** The datasets its checks read, in first-seen order (normally one). */
  datasets: string[];
  /** Its checks in file order: line, then column. */
  checks: CheckSummary[];
  counts: StatusCounts;
}

export interface FolderNode {
  kind: "folder";
  /** The label: one segment with a trailing "/", or the root's whole path. "" for an unnamed root. */
  name: string;
  /** The folder's path with a trailing "/"; "" for an unnamed root. */
  path: string;
  /** Folders first, then files; each sorted by name. */
  children: TreeNode[];
  counts: StatusCounts;
}

export type TreeNode = FolderNode | FileNode;

function segmentsOf(file: string): string[] {
  return file.split("/");
}

/**
 * The longest common folder of every file, as segments (E6). `checks/a.yml`
 * alone gives `["checks"]`; `checks/…` and `shared/…` give `[]`. Segments are
 * kept as written: `..` is not resolved.
 */
export function commonFolder(files: readonly string[]): string[] {
  let common: string[] | null = null;
  for (const file of files) {
    const dirs = segmentsOf(file).slice(0, -1);
    if (common === null) {
      common = dirs;
      continue;
    }
    let i = 0;
    while (i < common.length && i < dirs.length && common[i] === dirs[i]) i += 1;
    common = common.slice(0, i);
  }
  return common ?? [];
}

interface Building {
  folders: Map<string, Building>;
  files: Map<string, CheckSummary[]>;
}

function emptyBuilding(): Building {
  return { folders: new Map(), files: new Map() };
}

function finish(name: string, path: string, building: Building): FolderNode {
  const folders = [...building.folders.entries()]
    .sort(([a], [b]) => byName(a, b))
    .map(([segment, child]) => finish(`${segment}/`, `${path}${segment}/`, child));
  const files = [...building.files.entries()]
    .sort(([a], [b]) => byName(a, b))
    .map(([fileName, checks]): FileNode => {
      const ordered = [...checks].sort(
        (x, y) => x.location.line - y.location.line || x.location.column - y.location.column,
      );
      const datasets = [...new Set(ordered.map((c) => c.dataset))];
      return {
        kind: "file",
        name: fileName,
        path: `${path}${fileName}`,
        datasets,
        checks: ordered,
        counts: countStatuses(ordered),
      };
    });
  const children: TreeNode[] = [...folders, ...files];
  const all = children.flatMap((child) => (child.kind === "file" ? child.checks : collect(child)));
  return { kind: "folder", name, path, children, counts: countStatuses(all) };
}

function collect(folder: FolderNode): CheckSummary[] {
  return folder.children.flatMap((child) => (child.kind === "file" ? child.checks : collect(child)));
}

/**
 * The tree of `checks` under `root` (segments from `commonFolder` over every
 * loaded check, so the root stays put while filtering). Every check's file
 * starts with the root, because the root is common to all loaded files.
 */
export function buildTree(checks: readonly CheckSummary[], root: readonly string[]): FolderNode {
  const top = emptyBuilding();
  for (const check of checks) {
    const segments = segmentsOf(check.location.file).slice(root.length);
    const fileName = segments.pop() ?? check.location.file;
    let node = top;
    for (const segment of segments) {
      let next = node.folders.get(segment);
      if (next === undefined) {
        next = emptyBuilding();
        node.folders.set(segment, next);
      }
      node = next;
    }
    const list = node.files.get(fileName);
    if (list === undefined) node.files.set(fileName, [check]);
    else list.push(check);
  }
  const rootPath = root.length === 0 ? "" : `${root.join("/")}/`;
  return finish(rootPath, rootPath, top);
}

/** Problems a node holds: it is open on load (E5). */
export function hasProblems(counts: StatusCounts): boolean {
  return counts.fail + counts.error + counts.warn > 0;
}

/** The console's word for each status (`output/console.py`), and the overview's order. */
export const COUNT_WORDS: Readonly<Record<Status, string>> = {
  fail: "fail",
  error: "error",
  warn: "warn",
  none: "no result",
  skipped: "skipped",
  pass: "pass",
};

/** `18 checks · 6 fail · 2 warn · 10 pass`: the total, then non-zero counts, problems first (D3). */
export function countsText(counts: StatusCounts): string {
  const total = `${String(counts.total)} ${counts.total === 1 ? "check" : "checks"}`;
  const parts = STATUS_ORDER.filter((s) => counts[s] > 0).map((s) => `${String(counts[s])} ${COUNT_WORDS[s]}`);
  return [total, ...parts].join(" · ");
}
