/**
 * The one load/refresh hook for every page (spec 004, D14 and decision 8).
 *
 * A page names its requests as independent slots. `reload` starts every slot
 * again; only the newest round may write state, so an older answer that
 * arrives late is dropped (the generation guard). `busy` is true until every
 * slot of the newest round has settled. A one-minute clock re-renders ages
 * and fetches nothing: the page never polls.
 *
 * Follow-up requests a page makes itself (for example "Load older results")
 * take `capture()` before they start and write only while it still answers
 * true, so an answer that lands after a refresh is dropped too.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { failureOf, type ApiFailure } from "../api/api";

export type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "failed"; failure: ApiFailure };

export type Requests<S> = { readonly [K in keyof S]: () => Promise<S[K]> };
export type Slots<S> = { [K in keyof S]: Load<S[K]> };

export interface Loads<S> {
  slots: Slots<S>;
  busy: boolean;
  /** The clock the page renders ages against (epoch ms). */
  now: number;
  /** Increments on every reload; state a page keeps per round is tagged with it. */
  generation: number;
  reload: () => void;
  /** A guard for a follow-up request: true while no reload has started since. */
  capture: () => () => boolean;
}

/** Ages move on while the page is open; re-render them once a minute. */
export const TICK_MS = 60_000;

function loadingSlots<S>(requests: Requests<S>): Slots<S> {
  const slots = {} as Slots<S>;
  for (const key of Object.keys(requests) as (keyof S)[]) slots[key] = { state: "loading" };
  return slots;
}

export function useLoads<S>(requests: Requests<S>): Loads<S> {
  // The latest request functions; reload always uses these.
  const latest = useRef(requests);
  latest.current = requests;
  const [slots, setSlots] = useState<Slots<S>>(() => loadingSlots(requests));
  const [busy, setBusy] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [generation, setGeneration] = useState(0);
  const counter = useRef(0);

  const capture = useCallback(() => {
    const mine = counter.current;
    return () => mine === counter.current;
  }, []);

  const reload = useCallback(() => {
    counter.current += 1;
    const current = capture();
    setGeneration(counter.current);
    setBusy(true);
    const requestsNow = latest.current;
    const keys = Object.keys(requestsNow) as (keyof S)[];
    const settled = keys.map((key) =>
      requestsNow[key]().then(
        (data) => {
          if (current()) setSlots((prev) => ({ ...prev, [key]: { state: "ok", data } }));
        },
        (error: unknown) => {
          if (current()) setSlots((prev) => ({ ...prev, [key]: { state: "failed", failure: failureOf(error) } }));
        },
      ),
    );
    void Promise.all(settled).then(() => {
      if (current()) {
        setNow(Date.now());
        setBusy(false);
      }
    });
  }, [capture]);

  useEffect(() => {
    reload();
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, TICK_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [reload]);

  return { slots, busy, now, generation, reload, capture };
}
