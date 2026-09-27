/**
 * "Load older results" on a check's page (spec 004, D13 and D14).
 *
 * The first page of history comes from the page's `useLoads` round; older
 * pages are fetched here and belong to the round that fetched them, so a
 * refresh drops them. An answer that lands after a refresh is dropped too.
 */
import { useMemo, useState } from "react";
import { failureOf, getHistory, type ApiFailure } from "../../api/api";
import type { HistoryEntry, HistoryPage } from "../../api/types";

/** One page of history: the API's maximum (D13). */
export const HISTORY_LIMIT = 200;

interface Older {
  generation: number;
  items: HistoryEntry[];
  cursor: string | null;
  busy: boolean;
  failure: ApiFailure | null;
}

export interface OlderHistory {
  /** The first page followed by every older page loaded this round, newest first. */
  entries: HistoryEntry[];
  /** Where the next older page starts; null when there is none. */
  cursor: string | null;
  /** True while an older page is being fetched. */
  loading: boolean;
  /** Why the last older page failed, until the next attempt. */
  failure: ApiFailure | null;
  canLoadOlder: boolean;
  loadOlder: () => void;
}

export function useOlderHistory({
  id,
  firstPage,
  busy,
  generation,
  capture,
}: {
  id: string;
  firstPage: HistoryPage | null;
  /** The page's round is still loading. */
  busy: boolean;
  generation: number;
  capture: () => () => boolean;
}): OlderHistory {
  const [olderState, setOlder] = useState<Older | null>(null);
  // Older pages belong to the round that fetched them; a refresh drops them (D14).
  const older = olderState !== null && olderState.generation === generation ? olderState : null;

  const entries = useMemo(
    () => (firstPage === null ? [] : [...firstPage.items, ...(older?.items ?? [])]),
    [firstPage, older],
  );
  const cursor = older !== null ? older.cursor : (firstPage?.next_cursor ?? null);

  // While a refresh is in flight the first page on screen is the previous
  // round's: its cursor would append results the new first page may also hold,
  // or skip ones it lacks. Paging waits for the round to settle (D13, D14).
  const canLoadOlder = cursor !== null && !busy && older?.busy !== true;

  const loadOlder = (): void => {
    if (cursor === null || !canLoadOlder) return;
    const current = capture();
    const round = generation;
    const base = older?.items ?? [];
    setOlder({ generation: round, items: base, cursor, busy: true, failure: null });
    getHistory(id, HISTORY_LIMIT, cursor).then(
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
