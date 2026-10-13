import type { ReactElement } from "react";

/**
 * A neutral "Retired" marker (spec 037 S12/S13): a check gone from the
 * project's files, kept for its history. Styled apart from the outcome
 * badges (`StatusBadge`), like `DisabledBadge`: retired is not an outcome.
 */
export function RetiredBadge(): ReactElement {
  const text = "Retired — no longer in the loaded check files; kept for its history";
  return (
    <span className="badge badge--retired" title={text} aria-label={text}>
      Retired
    </span>
  );
}
