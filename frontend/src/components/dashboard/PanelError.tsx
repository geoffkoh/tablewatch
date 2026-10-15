import type { ReactElement } from "react";

/**
 * A Dashboard panel's own failure (spec 042 K-D5): one line, "Could not load
 * <panel>.", with its own Retry — never the full-page `LoadError`, and never
 * hiding the other panels or the check table.
 */
export function PanelError({ what, onRetry }: { what: string; onRetry: () => void }): ReactElement {
  return (
    <p className="dashboard-panel__error" role="alert">
      {`Could not load ${what}.`}{" "}
      <button type="button" className="button" onClick={onRetry}>
        Retry
      </button>
    </p>
  );
}
