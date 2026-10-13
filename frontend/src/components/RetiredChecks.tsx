import type { ReactElement } from "react";
import type { RetiredCheckSummary } from "../api/types";
import { checkHref } from "../lib/route";
import { statusOf } from "../lib/status";
import { DisabledBadge } from "./DisabledBadge";
import { ResultValue } from "./LatestResult";
import { RetiredBadge } from "./RetiredBadge";
import { StatusBadge } from "./StatusIcon";

/**
 * One retired check (spec 037 S12): the same row shape as a loaded check's
 * (`ExplorerTree`'s `CheckRow`), with "Retired" alongside "Disabled" — a
 * retired check is always `enabled: false` — and no file, so no dataset or
 * nesting under one.
 */
function RetiredRow({ item }: { item: RetiredCheckSummary }): ReactElement {
  const status = statusOf(item);
  const latest = item.latest;
  const measured =
    latest !== null && (latest.outcome === "pass" || latest.outcome === "warn" || latest.outcome === "fail")
      ? latest
      : null;
  return (
    <li className={`tree__check row--${status}`} data-check-id={item.id} data-status={status}>
      <StatusBadge status={status} />
      <span className="tree__check-text">
        <a className="check__name" href={checkHref(item.id)}>
          {item.name}
        </a>{" "}
        <RetiredBadge /> <DisabledBadge />
        {item.expression !== null && item.expression !== item.name && (
          <code className="check__expression">{item.expression}</code>
        )}
      </span>
      {measured !== null && (
        <span className="tree__value">
          <ResultValue result={measured} />
        </span>
      )}
    </li>
  );
}

function plural(n: number): string {
  return `${String(n)} ${n === 1 ? "check" : "checks"}`;
}

/**
 * The "Show retired" toggle's list (spec 037 S12): every retired check that
 * matches the search box, as a flat section below the tree — a retired check
 * has no current file to nest it under.
 */
export function RetiredChecks({ items }: { items: readonly RetiredCheckSummary[] }): ReactElement {
  return (
    <div className="retired-section" aria-label="Retired checks">
      <p className="retired-section__heading">
        {items.length === 0 ? "No retired checks match." : `${plural(items.length)} retired.`}
      </p>
      {items.length > 0 && (
        <ul className="tree__checks retired-list">
          {items.map((item) => (
            <RetiredRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}
