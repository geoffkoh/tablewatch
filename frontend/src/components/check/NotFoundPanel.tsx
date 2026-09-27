import type { ReactElement } from "react";

/** Neither loaded nor recorded: the id is unknown to this server. */
export function NotFoundPanel({ id, projectBroken }: { id: string; projectBroken: boolean }): ReactElement {
  return (
    <section className="panel" aria-labelledby="check-heading">
      <h1 id="check-heading" className="check-title">
        Check not found
      </h1>
      <p>
        No check with the id <code>{id}</code> is loaded, and no results are recorded for it.
      </p>
      {projectBroken && (
        <p className="quiet">Some check files did not load, so the check may be in one of them. See the overview.</p>
      )}
      <p>
        <a href="/">Go to the overview</a>
      </p>
    </section>
  );
}
