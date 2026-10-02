import type { ReactElement } from "react";
import { absolute, ago, sincePoint } from "../lib/time";

/**
 * A relative age ("3 hours ago") in a `<time>` whose `datetime` is the API's
 * UTC string, unchanged. The full time, in the viewer's zone with the zone
 * named, shows on hover (title) and on keyboard focus (CSS tooltip).
 */
export function Ago({ iso, now }: { iso: string; now: number }): ReactElement {
  const full = absolute(iso);
  return (
    <time className="time" dateTime={iso} title={full} data-full={full} tabIndex={0}>
      {ago(iso, now)}
    </time>
  );
}

/**
 * A streak's start ("Failing since 10:05 today", "… since Sep 19"): a point
 * in time, never an age (spec 017 P2). The same `<time>` element as `Ago`.
 */
export function Since({ iso, now, prefix }: { iso: string; now: number; prefix: string }): ReactElement {
  const full = absolute(iso);
  return (
    <time className="time" dateTime={iso} title={full} data-full={full} tabIndex={0}>
      {`${prefix} `}
      {sincePoint(iso, now)}
    </time>
  );
}
