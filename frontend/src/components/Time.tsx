import type { ReactElement } from "react";
import { absolute, ago } from "../lib/time";

/**
 * A relative age ("3 hours ago") in a `<time>` whose `datetime` is the API's
 * UTC string, unchanged. The full time, in the viewer's zone with the zone
 * named, shows on hover (title) and on keyboard focus (CSS tooltip).
 */
export function Ago({ iso, now, prefix }: { iso: string; now: number; prefix?: string }): ReactElement {
  const full = absolute(iso);
  return (
    <time className="time" dateTime={iso} title={full} data-full={full} tabIndex={0}>
      {prefix === undefined ? "" : `${prefix} `}
      {ago(iso, now)}
    </time>
  );
}
