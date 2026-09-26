import type { ReactElement } from "react";

/** Any path the UI does not know (W3). Later pages arrive as client routes. */
export function NotFound({ path }: { path: string }): ReactElement {
  return (
    <>
      <header className="app-header">
        <div className="app-header__inner">
          <p className="brand">
            <span className="brand__product">tablewatch</span>
          </p>
        </div>
      </header>
      <main id="main" className="page">
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
      </main>
    </>
  );
}
