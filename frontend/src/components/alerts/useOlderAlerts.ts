/**
 * "Load more" on the Alerts page (spec 041 P5), the same shape as the check
 * page's `useOlderHistory`: the first page comes from the page's `useLoads`
 * round; older pages are fetched here and belong to the round that fetched
 * them, so a refresh — or a change of the event filter, which reloads too —
 * drops them. An answer that lands after either is dropped as well.
 */
import { useMemo, useState } from "react";
import { failureOf, listAlerts, type ApiFailure } from "../../api/api";
import type { Alert, AlertPage } from "../../api/types";
import { ALERTS_LIMIT, alertsEventParam, type AlertFilter } from "../../lib/alerts";

interface Older {
  generation: number;
  items: Alert[];
  cursor: string | null;
  busy: boolean;
  failure: ApiFailure | null;
}

export interface OlderAlerts {
  /** The first page followed by every older page loaded this round, newest first. */
  entries: Alert[];
  /** Where the next older page starts; null when there is none. */
  cursor: string | null;
  /** True while an older page is being fetched. */
  loading: boolean;
  /** Why the last older page failed, until the next attempt. */
  failure: ApiFailure | null;
  canLoadOlder: boolean;
  loadOlder: () => void;
}

export function useOlderAlerts({
  filter,
  firstPage,
  busy,
  generation,
  capture,
}: {
  filter: AlertFilter;
  firstPage: AlertPage | null;
  /** The page's round is still loading. */
  busy: boolean;
  generation: number;
  capture: () => () => boolean;
}): OlderAlerts {
  const [olderState, setOlder] = useState<Older | null>(null);
  // Older pages belong to the round that fetched them; a refresh, or a
  // changed filter (both bump `generation`), drops them.
  const older = olderState !== null && olderState.generation === generation ? olderState : null;

  const entries = useMemo(
    () => (firstPage === null ? [] : [...firstPage.items, ...(older?.items ?? [])]),
    [firstPage, older],
  );
  const cursor = older !== null ? older.cursor : (firstPage?.next_cursor ?? null);

  // While a refresh (or filter change) is in flight the page on screen is the
  // previous round's: its cursor would append alerts the new first page may
  // also hold, or skip ones it lacks. Paging waits for the round to settle.
  const canLoadOlder = cursor !== null && !busy && older?.busy !== true;

  const loadOlder = (): void => {
    if (cursor === null || !canLoadOlder) return;
    const current = capture();
    const round = generation;
    const base = older?.items ?? [];
    setOlder({ generation: round, items: base, cursor, busy: true, failure: null });
    listAlerts(ALERTS_LIMIT, alertsEventParam(filter), cursor).then(
      (page) => {
        if (current()) {
          setOlder({ generation: round, items: [...base, ...page.items], cursor: page.next_cursor, busy: false, failure: null });
        }
      },
      (error: unknown) => {
        if (current()) setOlder({ generation: round, items: base, cursor, busy: false, failure: failureOf(error) });
      },
    );
  };

  return {
    entries,
    cursor,
    loading: older?.busy ?? false,
    failure: older?.failure ?? null,
    canLoadOlder,
    loadOlder,
  };
}
