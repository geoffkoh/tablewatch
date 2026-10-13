import type { ReactElement } from "react";

/**
 * A neutral "Disabled" marker (spec 036 S15): a check with `enabled: false`
 * in its file is listed with its last result but never run. Styled apart
 * from the outcome badges (`StatusBadge`) — disabled is not an outcome, so
 * it never borrows a status colour, in light or dark.
 */
export function DisabledBadge(): ReactElement {
  const text = "Disabled — enabled: false in its file; not run";
  return (
    <span className="badge badge--disabled" title={text} aria-label={text}>
      Disabled
    </span>
  );
}
