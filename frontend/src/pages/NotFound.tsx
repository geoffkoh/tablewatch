import type { ReactElement } from "react";
import { AppShell } from "../components/AppShell";

/**
 * Any path the UI does not know (W3). Later pages arrive as client routes.
 * It still wears the shell (spec 039, P-D2), with no section current (N1)
 * and no problems count: it makes no request of its own, so there is
 * nothing to refresh and the nav's Checks badge stays hidden.
 */
export function NotFound({ path }: { path: string }): ReactElement {
  return (
    <AppShell current={null} project={null} now={Date.now()} busy={false} onRefresh={() => undefined} projectIsHeading={false}>
      <section className="panel" aria-labelledby="not-found-heading">
        <h1 id="not-found-heading" className="panel__title">
          Page not found
        </h1>
        <p>
          There is no page at <code>{path}</code>.
        </p>
        <p>
          <a href="/">Go to the overview</a>
        </p>
      </section>
    </AppShell>
  );
}
