import type { ReactElement } from "react";
import type { ApiFailure } from "../api/api";

/**
 * A request that failed (O9). Shown instead of counts and rows, never next
 * to stale or empty ones that could pass for "nothing failing".
 */
export function LoadError({ what, failure, onRetry }: { what: string; failure: ApiFailure; onRetry: () => void }): ReactElement {
  return (
    <section className="panel load-error" role="alert" aria-labelledby="load-error-heading">
      <h2 id="load-error-heading" className="panel__title">
        Could not load {what}
      </h2>
      <p className="load-error__message">{failure.message}</p>
      {failure.kind === "http" && (
        <p className="quiet">
          HTTP {failure.status}
          {failure.code !== null && <> · {failure.code}</>}
        </p>
      )}
      <p className="quiet">Nothing below is shown until it loads, so no count can be mistaken for the whole picture.</p>
      <button type="button" className="button" onClick={onRetry}>
        Try again
      </button>
    </section>
  );
}
