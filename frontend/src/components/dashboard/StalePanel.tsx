/**
 * "Not scanned recently" (spec 042 K-D3): derived in the browser from the
 * `/checks` data the page already loads (`lib/stale.ts`), so it has no
 * request of its own and no failure state (a `/checks` failure already hides
 * the checks table and this page, O9). None stale reads "Every dataset was
 * scanned within a day of the latest run."
 */
import type { ReactElement } from "react";
import { datasetHref } from "../../lib/datasets";
import type { StaleDataset } from "../../lib/stale";
import { Ago } from "../Time";

function StaleRow({ row, now }: { row: StaleDataset; now: number }): ReactElement {
  return (
    <li className="dashboard-stale__row" data-dataset={row.dataset} data-datasource={row.datasource}>
      <a href={datasetHref(row.datasource, row.dataset)}>
        {row.dataset} · {row.datasource}
      </a>
      {" — "}
      {row.lastScanned === null ? (
        "never scanned"
      ) : (
        <>
          last scanned <Ago iso={row.lastScanned} now={now} />
        </>
      )}
    </li>
  );
}

export function StalePanel({ rows, now }: { rows: readonly StaleDataset[]; now: number }): ReactElement {
  return (
    <section className="panel dashboard-panel" aria-labelledby="stale-heading">
      <h2 id="stale-heading" className="panel__title">
        Not scanned recently
      </h2>
      {rows.length === 0 ? (
        <p className="empty">Every dataset was scanned within a day of the latest run.</p>
      ) : (
        <ul className="dashboard-stale" aria-label="Not scanned recently">
          {rows.map((row) => (
            <StaleRow key={`${row.datasource}\u0000${row.dataset}`} row={row} now={now} />
          ))}
        </ul>
      )}
    </section>
  );
}
