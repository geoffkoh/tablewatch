/** How a run's `selection` reads: every key shown, unknown keys raw (O8, C1). */
import type { Selection } from "../api/types";

const KNOWN: readonly (readonly [string, string])[] = [
  ["paths", "paths"],
  ["tags", "tags"],
  ["datasources", "datasources"],
  ["excludes", "excludes"],
  ["check_ids", "check ids"],
];

export interface SelectionPart {
  key: string;
  label: string;
  values: readonly string[];
}

/** The keys in a fixed order (known first, then unknown by name); empty = every check. */
export function selectionParts(selection: Selection): SelectionPart[] {
  const parts: SelectionPart[] = [];
  const known = new Set<string>();
  for (const [key, label] of KNOWN) {
    known.add(key);
    const values = selection[key];
    if (values !== undefined) parts.push({ key, label, values });
  }
  for (const key of Object.keys(selection).sort()) {
    const values = selection[key];
    if (!known.has(key) && values !== undefined) parts.push({ key, label: key, values });
  }
  return parts;
}

/** "paths: checks/sales; tags: pii", or "all checks". */
export function describeSelection(selection: Selection): string {
  const parts = selectionParts(selection);
  if (parts.length === 0) return "all checks";
  return parts
    .map((p) => `${p.label}: ${p.values.length > 0 ? p.values.join(", ") : "(none)"}`)
    .join("; ");
}
