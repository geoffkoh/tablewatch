/**
 * The check explorer's pure parts (spec 015): the query it keeps in the URL,
 * the search and status filter, the `checks/` tree, and the counts on every
 * folder and file. No React and no DOM here, so each rule is tested alone.
 */
import type { CheckSummary } from "../api/types";
import { countStatuses, STATUS_ORDER, statusOf, type Status, type StatusCounts } from "./status";

/** The longest search kept from a URL or the box (E12). */
export const MAX_QUERY_LENGTH = 200;

/** What the explorer shows: a search text and the selected statuses (none selected means all). */
export interface ExplorerQuery {
  q: string;
  statuses: Status[];
}

function isStatus(value: string): value is Status {
  return (STATUS_ORDER as readonly string[]).includes(value);
}

/** Selected statuses, deduplicated, in problem-first order. */
export function orderStatuses(statuses: Iterable<Status>): Status[] {
  const chosen = new Set(statuses);
  return STATUS_ORDER.filter((s) => chosen.has(s));
}

/** `q` cut to its limit by code point, so an emoji is never split in half. */
function cutQuery(q: string): string {
  return Array.from(q).slice(0, MAX_QUERY_LENGTH).join("");
}

/**
 * The query from `location.search`. Unknown statuses are ignored and `q` is
 * cut to 200 characters (E12). `q` is kept as written: the box shows it.
 */
export function parseExplorerQuery(search: string): ExplorerQuery {
  const params = new URLSearchParams(search);
  const q = cutQuery(params.get("q") ?? "");
  const statuses = orderStatuses(params.getAll("status").filter(isStatus));
  return { q, statuses };
}

/**
 * The query as a `location.search` string: `?q=…&status=…`, or "" for
 * everything. A search of only spaces is no search.
 */
export function explorerSearch(query: ExplorerQuery): string {
  const params = new URLSearchParams();
  if (query.q.trim() !== "") params.set("q", cutQuery(query.q));
  for (const status of orderStatuses(query.statuses)) params.append("status", status);
  const text = params.toString();
  return text === "" ? "" : `?${text}`;
}

/** True when the query narrows anything. */
export function isFiltering(query: ExplorerQuery): boolean {
  return query.q.trim() !== "" || query.statuses.length > 0;
}

/**
 * Case-insensitive substring of name, expression, dataset, file path or id;
 * leading and trailing spaces ignored (E8).
 */
export function matchesText(check: CheckSummary, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (needle === "") return true;
  return [check.name, check.expression, check.dataset, check.location.file, check.id].some((field) =>
    field.toLowerCase().includes(needle),
  );
}

/** Search and status together (E10: AND). No status selected means all. */
export function filterChecks(checks: readonly CheckSummary[], query: ExplorerQuery): CheckSummary[] {
  const statuses = new Set(query.statuses);
  return checks.filter((c) => matchesText(c, query.q) && (statuses.size === 0 || statuses.has(statusOf(c))));
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

/** Names compare without case first, then exactly, so the order is the same everywhere. */
function byName(a: string, b: string): number {
  const la = a.toLowerCase();
  const lb = b.toLowerCase();
  if (la !== lb) return la < lb ? -1 : 1;
  if (a === b) return 0;
  return a < b ? -1 : 1;
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
