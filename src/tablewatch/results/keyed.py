"""Keyed runs: one logical run that a retry resumes (`--run-key`, spec 034).

A keyed run's row is written first, each dataset's results are recorded as
its scan ends, and the row is finished last. A later attempt under the same
key skips the datasets already recorded with an answer about the data, and
a completed key does nothing unless `--rerun` starts a new attempt. One
process holds a key at a time.

Internal: `api.execute` drives it; the runner never learns about keys.
"""

from __future__ import annotations

import hashlib
import logging
import socket
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tablewatch._version import __version__
from tablewatch.checks.model import Check, Dataset, Outcome, check_outcome
from tablewatch.engine.runner import CheckResult, RunResult, SkippedDataset, username
from tablewatch.errors import TablewatchError
from tablewatch.jsonvalues import utc
from tablewatch.results.models import (
    MAX_RUN_KEY,
    CheckResultRow,
    CheckRow,
    ClauseResultRow,
    DatasetRunRow,
    RunLockRow,
    RunRow,
)
from tablewatch.results.outbox import forget_unsent, write_alerts
from tablewatch.results.store import (
    PageKey,
    ResultStore,
    StoreError,
    fit_row,
    open_store,
    reading,
    register_all,
    result_rows,
)

log = logging.getLogger(__name__)

# The SQLite lock: the holder refreshes it this often, and a lock not
# refreshed for STALE_AFTER was left by a process that died (spec 034 D5).
HEARTBEAT_EVERY = timedelta(seconds=20)
STALE_AFTER = timedelta(seconds=120)

# The exit code of a run that could not do its job (`RunResult.exit_code`).
EXIT_COULD_NOT = 2

# An error is not an answer about the data: a retry owes it another scan.
_DONE = frozenset(
    {Outcome.PASS.value, Outcome.WARN.value, Outcome.FAIL.value, Outcome.SKIPPED.value}
)


class RunKeyError(TablewatchError):
    """A keyed run could not start or resume, so nothing ran (exit 2)."""


def check_run_key(run_key: str) -> None:
    """Raise `ValueError` for a key the store cannot hold: a usage mistake."""
    if not run_key.strip():
        raise ValueError("--run-key must not be empty")
    if len(run_key) > MAX_RUN_KEY:
        raise ValueError(
            f"--run-key must be at most {MAX_RUN_KEY} characters (got {len(run_key)})"
        )
    if "\0" in run_key:
        raise ValueError("--run-key must not contain a NUL character")


@dataclass(frozen=True)
class Completed:
    """The latest attempt under the key finished: what it recorded."""

    run_id: str
    finished_at: datetime
    exit_code: int


class KeyedRun:
    """The store side of one attempt under a run key.

    Opening it migrates the store, takes the key's lock, and begins a new
    run row or resumes an unfinished one. `record_dataset` is called from
    the runner's threads; `finish` closes the row.
    """

    def __init__(
        self,
        url: str,
        project_root: Path,
        project: str,
        run_key: str,
        *,
        rerun: bool,
        trigger: str,
        selection: dict[str, Any],
        now: datetime,
        notify: bool = True,
    ) -> None:
        check_run_key(run_key)
        self.project = project
        self.run_key = run_key
        # Whether datasets write their state changes to the outbox; off
        # under `--no-notify`, so no later attempt sends them (spec 035 D2).
        self.notify = notify
        self._write = threading.Lock()
        self._lock: _Lock | None = None
        try:
            self.store: ResultStore = open_store(url, project_root)
        except StoreError as exc:
            raise RunKeyError(_reason(exc)) from exc
        try:
            self._lock = _lock_for(self.store, project, run_key)
            self._begin(rerun, trigger, selection, now)
        except StoreError as exc:
            self.close()
            raise RunKeyError(_reason(exc)) from exc
        except BaseException:
            self.close()
            raise

    # --- beginning ---

    def _begin(
        self, rerun: bool, trigger: str, selection: dict[str, Any], now: datetime
    ) -> None:
        self.completed: Completed | None = None
        self.done: dict[tuple[str, str], SkippedDataset] = {}
        # Datasets an earlier attempt recorded as `error`: rescanned when
        # selected, and still counted when not (spec 034 D2).
        self.unanswered: dict[tuple[str, str], SkippedDataset] = {}
        self.recorded_checks: set[str] = set()
        with reading(self.store.engine), Session(self.store.engine) as session:
            latest = session.scalars(
                select(RunRow)
                .where(RunRow.project == self.project, RunRow.run_key == self.run_key)
                .order_by(RunRow.started_at.desc(), RunRow.id.desc())
                .limit(1)
            ).one_or_none()
            if latest is not None and not rerun:
                # Exit 2 is "could not do its job" — an error outcome, or a
                # dataset that could not be recorded — which is what a retry
                # is for, so such a run resumes rather than being complete.
                if (
                    latest.exit_code is not None
                    and latest.exit_code != EXIT_COULD_NOT
                    and latest.finished_at is not None
                ):
                    self.completed = Completed(
                        latest.id, utc(latest.finished_at), latest.exit_code
                    )
                    self.run_id, self.started_at = latest.id, utc(latest.started_at)
                    self._read_done(session)
                    return
                # SQLite returns the moment without its zone; it was stored
                # in UTC, and the run's clock arithmetic needs it aware.
                self.run_id, self.started_at = latest.id, utc(latest.started_at)
                self.resumed = True
                self._read_done(session)
                if latest.exit_code is not None:
                    self._reopen(session)
                return
        self.resumed = False
        self.run_id, self.started_at = uuid.uuid4().hex, now
        row = RunRow(
            id=self.run_id,
            project=self.project,
            started_at=now,
            trigger=trigger,
            hostname=socket.gethostname(),
            username=username(),
            version=__version__,
            selection=selection,
            run_key=self.run_key,
        )
        fit_row(row)
        with (
            reading(self.store.engine),
            Session(self.store.engine) as session,
            session.begin(),
        ):
            session.add(row)

    def _read_done(self, session: Session) -> None:
        """The datasets an earlier attempt answered, with their counts."""
        datasets = session.scalars(
            select(DatasetRunRow).where(DatasetRunRow.run_id == self.run_id)
        ).all()
        counts: dict[tuple[str, str], dict[Outcome, int]] = {}
        rows = session.execute(
            select(
                CheckResultRow.datasource,
                CheckResultRow.dataset,
                CheckResultRow.outcome,
                func.count(),
            )
            .where(CheckResultRow.run_id == self.run_id)
            .group_by(
                CheckResultRow.datasource,
                CheckResultRow.dataset,
                CheckResultRow.outcome,
            )
        )
        for datasource, dataset, outcome, n in rows:
            counts.setdefault((datasource, dataset), {})[Outcome(outcome)] = n
        for row in datasets:
            key = (row.datasource, row.dataset)
            recorded = SkippedDataset(
                row.datasource, row.dataset, Outcome(row.outcome), counts.get(key, {})
            )
            (self.done if row.outcome in _DONE else self.unanswered)[key] = recorded
        self.recorded_checks = set(
            session.scalars(
                select(CheckRow.check_hash)
                .join(CheckResultRow, CheckResultRow.check_id == CheckRow.id)
                .where(CheckResultRow.run_id == self.run_id)
            )
        )

    def _reopen(self, session: Session) -> None:
        """Mark a finished exit-2 run unfinished again while it is retried,
        so run reads never show totals its rows no longer match (D8)."""
        session.execute(
            update(RunRow)
            .where(RunRow.id == self.run_id)
            .values(
                finished_at=None,
                outcome=None,
                exit_code=None,
                total=None,
                passed=None,
                warned=None,
                failed=None,
                errored=None,
            )
        )
        session.commit()  # the session's reads began its transaction

    def skipped(self, scanned: set[tuple[str, str]]) -> tuple[SkippedDataset, ...]:
        """What this attempt counts but did not scan: the datasets already
        answered, and those left in `error` that it did not select again."""
        return (
            *self.done.values(),
            *(u for key, u in self.unanswered.items() if key not in scanned),
        )

    def is_done(self, check: Check) -> bool:
        return (check.dataset.datasource, check.dataset.name) in self.done

    # --- recording ---

    def record_dataset(self, dataset: Dataset, results: list[CheckResult]) -> None:
        """Record one dataset's results in one transaction, replacing any
        earlier attempt's rows for it (an `error` being retried), with the
        state changes its notifiers should hear (spec 035 D2)."""
        rows = result_rows(results)
        for row in rows:
            row.run_id = self.run_id
        finished = datetime.now(UTC)
        record = DatasetRunRow(
            run_id=self.run_id,
            datasource=dataset.datasource,
            dataset=dataset.name,
            started_at=finished
            - timedelta(
                milliseconds=max((r.duration_ms for r in results), default=0.0)
            ),
            finished_at=finished,
            outcome=_worst(results),
            version=__version__,
        )
        fit_row(record)
        with self._write:
            # Under the write lock: the Postgres lock's connection is not
            # shared between threads.
            self.check_lock()
            with (
                reading(self.store.engine),
                Session(self.store.engine) as session,
                session.begin(),
            ):
                self._forget(session, dataset)
                register_all(session, self.project, results, rows)
                session.add_all([*rows, record])
                if self.notify:
                    session.flush()
                    write_alerts(
                        session,
                        self.store,
                        project=self.project,
                        run=PageKey(self.started_at, self.run_id),
                        resumed=self.resumed,
                        results=results,
                        rows=rows,
                    )

    def _forget(self, session: Session, dataset: Dataset) -> None:
        earlier = select(CheckResultRow.id).where(
            CheckResultRow.run_id == self.run_id,
            CheckResultRow.datasource == dataset.datasource,
            CheckResultRow.dataset == dataset.name,
        )
        # Explicitly, not by cascade: SQLite enforces foreign keys only
        # when asked to. A change already sent stays: it is not sent twice.
        forget_unsent(
            session,
            self.run_id,
            select(CheckResultRow.check_id).where(
                CheckResultRow.run_id == self.run_id,
                CheckResultRow.datasource == dataset.datasource,
                CheckResultRow.dataset == dataset.name,
            ),
        )
        session.execute(
            delete(ClauseResultRow).where(ClauseResultRow.check_result_id.in_(earlier))
        )
        session.execute(
            delete(CheckResultRow).where(
                CheckResultRow.id.in_(earlier.scalar_subquery())
            )
        )
        session.execute(
            delete(DatasetRunRow).where(
                DatasetRunRow.run_id == self.run_id,
                DatasetRunRow.datasource == dataset.datasource,
                DatasetRunRow.dataset == dataset.name,
            )
        )

    def finish(self, run: RunResult) -> None:
        """Close the run row: its outcome over every dataset recorded under
        it, by any attempt. A sink: raising makes the exit code 2."""
        with self._write:
            self.check_lock()
        with (
            reading(self.store.engine),
            Session(self.store.engine) as session,
            session.begin(),
        ):
            tally: dict[str, int] = dict(
                session.execute(
                    select(CheckResultRow.outcome, func.count())
                    .where(CheckResultRow.run_id == self.run_id)
                    .group_by(CheckResultRow.outcome)
                ).all()
            )
            session.execute(
                update(RunRow)
                .where(RunRow.id == self.run_id)
                .values(
                    finished_at=run.finished_at,
                    outcome=str(run.outcome),
                    exit_code=run.exit_code(),
                    total=sum(tally.values()),
                    passed=tally.get(Outcome.PASS.value, 0),
                    warned=tally.get(Outcome.WARN.value, 0),
                    failed=tally.get(Outcome.FAIL.value, 0),
                    errored=tally.get(Outcome.ERROR.value, 0),
                )
            )

    def check_lock(self) -> None:
        """Raise `StoreError` if the key's lock has been lost (D12)."""
        if self._lock is not None and not self._lock.held():
            raise StoreError(self._lost())

    def _lost(self) -> str:
        return (
            f"results store: lost the lock on run key '{self.run_key}' (its "
            "connection dropped, or another process took it over)"
        )

    def close(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None
        self.store.close()

    def __enter__(self) -> KeyedRun:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _worst(results: Sequence[CheckResult]) -> str:
    # A dataset's checks fold as a check's clauses do: all skipped, skipped.
    return str(check_outcome([r.outcome for r in results]))


def _reason(exc: StoreError) -> str:
    return str(exc).removeprefix("results store: ")


# --- the lock ---


class _Lock:
    def held(self) -> bool:
        return True

    def release(self) -> None:
        raise NotImplementedError


def _lock_for(store: ResultStore, project: str, run_key: str) -> _Lock:
    if store.engine.dialect.name == "postgresql":
        return _AdvisoryLock(store, project, run_key)
    return _RowLock(store, project, run_key)


def _busy(run_key: str) -> RunKeyError:
    return RunKeyError(f"another process is already running run key '{run_key}'")


def advisory_key(project: str, run_key: str) -> int:
    """A stable 64-bit lock key: `hash()` differs between processes."""
    digest = hashlib.sha256(f"{project}\0{run_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class _AdvisoryLock(_Lock):
    """A session lock on its own connection: a process that dies frees it."""

    def __init__(self, store: ResultStore, project: str, run_key: str) -> None:
        self._key = advisory_key(project, run_key)
        with reading(store.engine):
            self._connection: Connection | None = store.engine.connect()
            try:
                taken = self._connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": self._key}
                )
                # The lock outlives the transaction; an idle open one would
                # meet idle_in_transaction_session_timeout.
                self._connection.commit()
            except BaseException:
                self._connection.close()
                raise
        if not taken:
            self._connection.close()
            self._connection = None
            raise _busy(run_key)

    def held(self) -> bool:
        """The lock lives as long as its connection: a dropped one lost it."""
        if self._connection is None:
            return False
        try:
            self._connection.execute(text("SELECT 1"))
            self._connection.commit()
        except Exception as exc:
            log.warning("run lock: its connection was lost (%s)", type(exc).__name__)
            return False
        return True

    def release(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": self._key}
            )
            self._connection.commit()
        except Exception as exc:  # closing the connection frees it anyway
            log.debug("run lock: unlock failed (%s)", type(exc).__name__)
        finally:
            self._connection.close()
            self._connection = None


class _RowLock(_Lock):
    """A row in `tablewatch_run_locks`, kept fresh by a heartbeat thread."""

    def __init__(self, store: ResultStore, project: str, run_key: str) -> None:
        self._engine = store.engine
        self._where = (RunLockRow.project == project, RunLockRow.run_key == run_key)
        self._owner = uuid.uuid4().hex
        self._lost = False
        now = datetime.now(UTC)
        with reading(store.engine):
            if not self._insert(project, run_key, now) and not self._steal(now):
                raise _busy(run_key)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._beat, name="tablewatch-run-lock", daemon=True
        )
        self._thread.start()

    def _insert(self, project: str, run_key: str, now: datetime) -> bool:
        try:
            with Session(self._engine) as session, session.begin():
                session.add(
                    RunLockRow(
                        project=project,
                        run_key=run_key,
                        owner=self._owner,
                        acquired_at=now,
                        heartbeat_at=now,
                    )
                )
        except IntegrityError:
            return False
        return True

    def _steal(self, now: datetime) -> bool:
        """Take over a lock whose holder stopped beating. Compare-and-swap on
        the owner, so of two processes that both saw it stale, one wins."""
        with Session(self._engine) as session, session.begin():
            row = session.execute(
                select(RunLockRow.owner, RunLockRow.heartbeat_at).where(*self._where)
            ).one_or_none()
            if row is None:  # released between the insert and here
                return False
            owner, heartbeat = row
            if utc(heartbeat) > now - STALE_AFTER:
                return False
            log.warning("run lock: taking over a lock left by a process that stopped")
            taken = session.execute(
                update(RunLockRow)
                .where(*self._where, RunLockRow.owner == owner)
                .values(owner=self._owner, acquired_at=now, heartbeat_at=now)
            )
            return bool(taken.rowcount == 1)  # type: ignore[attr-defined]

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_EVERY.total_seconds()):
            try:
                with Session(self._engine) as session, session.begin():
                    kept = session.execute(
                        update(RunLockRow)
                        .where(*self._where, RunLockRow.owner == self._owner)
                        .values(heartbeat_at=datetime.now(UTC))
                    )
                    if kept.rowcount != 1:  # type: ignore[attr-defined]
                        self._lost = True
                        return
            except Exception as exc:  # a missed beat is retried on the next
                log.debug("run lock: heartbeat failed (%s)", type(exc).__name__)

    def held(self) -> bool:
        return not self._lost

    def release(self) -> None:
        self._stop.set()
        self._thread.join()
        try:
            with Session(self._engine) as session, session.begin():
                session.execute(
                    delete(RunLockRow).where(
                        *self._where, RunLockRow.owner == self._owner
                    )
                )
        except Exception as exc:  # a stale lock is taken over after STALE_AFTER
            log.warning("run lock: could not release (%s)", type(exc).__name__)
