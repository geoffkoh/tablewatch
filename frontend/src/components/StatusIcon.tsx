import type { ReactElement } from "react";
import { STATUS_META, type Status } from "../lib/status";
import { StatusShape } from "./shapes";

export function StatusIcon({ status }: { status: Status }): ReactElement {
  return (
    <svg
      className={`icon icon--${status}`}
      viewBox="0 0 16 16"
      width="16"
      height="16"
      role="img"
      aria-label={STATUS_META[status].meaning}
      focusable="false"
    >
      <StatusShape status={status} />
    </svg>
  );
}

export function StatusBadge({ status }: { status: Status }): ReactElement {
  return (
    <span className={`badge status--${status}`}>
      <StatusIcon status={status} />
      <span className="badge-label">{STATUS_META[status].label}</span>
    </span>
  );
}
