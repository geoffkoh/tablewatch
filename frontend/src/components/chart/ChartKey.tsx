import type { ReactElement } from "react";
import type { KeyItem } from "../../lib/chart/legend";
import { StatusShape } from "../shapes";

/** A small drawing of a key item: the same shapes and classes the chart uses. */
function Swatch({ item }: { item: KeyItem }): ReactElement {
  let inner: ReactElement;
  switch (item.kind) {
    case "mark":
      inner = (
        <g className={`mark mark--${item.outcome}`} transform="translate(2 2) scale(0.75)">
          <StatusShape status={item.outcome} />
        </g>
      );
      break;
    case "band":
      inner = (
        <>
          <rect className={`chart__band chart__band--${item.severity}`} x="0" y="4" width="16" height="12" />
          <line className={`chart__boundary chart__boundary--${item.severity}`} x1="0" x2="16" y1="4" y2="4" />
        </>
      );
      break;
    case "marker":
      inner = (
        <g className="chart__marker">
          <line x1="8" x2="8" y1="0" y2="16" />
        </g>
      );
      break;
    case "streak":
      inner = (
        <g className="chart__streak">
          <path d="M1 12V6H15V12" />
        </g>
      );
      break;
  }
  return (
    <svg className="chart-key__swatch" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      {inner}
    </svg>
  );
}

/** Every shape the chart shows, with its name (D11). */
export function ChartKey({ items }: { items: readonly KeyItem[] }): ReactElement {
  return (
    <ul className="chart-key" aria-label="Chart key">
      {items.map((item) => (
        <li key={item.key} data-key={item.key}>
          <Swatch item={item} />
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  );
}
