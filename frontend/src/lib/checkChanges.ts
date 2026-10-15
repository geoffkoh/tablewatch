/**
 * The Dashboard's "Check changes" panel (spec 042 K-D4): wording for each
 * `ChangeKind` from `GET /check-changes`. `version` is set only for
 * `redefined`; every other kind ignores it.
 */
import type { CheckChange } from "../api/types";

/** "Added", "Definition changed (version 3)", "Disabled", "Retired", "Enabled again". */
export function checkChangeText(change: CheckChange): string {
  switch (change.kind) {
    case "added":
      return "Added";
    case "redefined":
      return `Definition changed (version ${String(change.version)})`;
    case "disabled":
      return "Disabled";
    case "retired":
      return "Retired";
    case "enabled":
      return "Enabled again";
  }
}
