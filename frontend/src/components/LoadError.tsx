import { useId, type ReactElement } from "react";
import type { ApiFailure } from "../api/api";

/**
 * A request that failed (O9). Shown instead of counts and rows, never next
 * to stale or empty ones that could pass for "nothing failing".
 *
 * `scope` says what the failure withholds. A `page` failure (the default)
 * stands in for everything below it; a `section` failure stays inside one
 * section of a page whose other sections loaded, and says so. `level` is the
 * heading level, so a failure nested in a section's `<h2>` can use `<h3>`.
 * The heading id comes from `useId`, so several failures on one page never
 * share an id.
 */
export function LoadError({
  what,
  failure,
  onRetry,
  level = 2,
  scope = "page",
}: {
  what: string;
  failure: ApiFailure;
  onRetry: () => void;
  level?: 2 | 3;
  scope?: "page" | "section";
}): ReactElement {
  const headingId = useId();
  const Heading = level === 3 ? "h3" : "h2";
  return (
    <section className="panel load-error" role="alert" aria-labelledby={headingId}>
      <Heading id={headingId} className="panel__title">
        Could not load {what}
      </Heading>
      <p className="load-error__message">{failure.message}</p>
      {failure.kind === "http" && (
        <p className="quiet">
          HTTP {failure.status}
          {failure.code !== null && <> · {failure.code}</>}
        </p>
      )}
      <p className="quiet">
        {scope === "page"
          ? "Nothing below is shown until it loads, so no count can be mistaken for the whole picture."
          : "Only this section is missing; the rest of the page loaded."}
      </p>
      <button type="button" className="button" onClick={onRetry}>
        Try again
      </button>
    </section>
  );
}
