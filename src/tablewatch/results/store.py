"""Reading and writing run history.

Opening a store brings its schema up to date (Alembic `upgrade head`), so
upgrading tablewatch never needs a separate migration step on a server.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, make_url, select
from sqlalchemy.orm import Session

from tablewatch.checks.model import Outcome
from tablewatch.engine.runner import ResultSink, RunResult
from tablewatch.results.models import CheckResultRow, RunRow

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def resolve_store_url(url: str, project_root: Path) -> URL:
    """Relative SQLite paths resolve against the project root, not the cwd."""
    parsed = make_url(url)
    database = parsed.database
    if parsed.get_backend_name() == "sqlite" and database and database != ":memory:":
        path = Path(database).expanduser()
        if not path.is_absolute():
            path = project_root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        parsed = parsed.set(database=str(path))
    return parsed


class ResultStore:
    """Run history in a SQL database, migrated to the current schema on open."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._migrate()

    @classmethod
    def open(cls, url: str, project_root: Path) -> ResultStore:
        return cls(create_engine(resolve_store_url(url, project_root)))

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> ResultStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _migrate(self) -> None:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def save(self, run: RunResult) -> None:
        row = RunRow(
            id=run.id,
            project=run.project,
            started_at=run.started_at,
            finished_at=run.finished_at,
            outcome=str(run.outcome),
            exit_code=run.exit_code(),
            trigger=run.trigger,
            hostname=run.hostname,
            username=run.username,
            version=run.version,
            selection=run.selection,
            total=len(run.results),
            passed=run.count(Outcome.PASS),
            warned=run.count(Outcome.WARN),
            failed=run.count(Outcome.FAIL),
            errored=run.count(Outcome.ERROR),
        )
        row.results = [
            CheckResultRow(
                check_id=r.check.id,
                check_name=r.check.name,
                expression=r.check.canonical,
                metric=r.check.metric.name,
                dataset=r.check.dataset.name,
                datasource=r.check.dataset.datasource,
                outcome=str(r.outcome),
                value=r.value,
                display_value=r.display_value,
                message=r.message,
                source=str(r.check.location),
                owner=r.check.dataset.owner,
                tags=list(r.check.dataset.tags),
                duration_ms=r.duration_ms,
            )
            for r in run.results
        ]
        with Session(self.engine) as session, session.begin():
            session.add(row)

    def recent_runs(self, limit: int = 20) -> list[RunRow]:
        with Session(self.engine) as session:
            statement = select(RunRow).order_by(RunRow.started_at.desc()).limit(limit)
            return list(session.scalars(statement))

    def matching_check_ids(self, prefix: str) -> list[str]:
        with Session(self.engine) as session:
            statement = (
                select(CheckResultRow.check_id)
                .where(CheckResultRow.check_id.startswith(prefix, autoescape=True))
                .distinct()
            )
            return sorted(session.scalars(statement))

    def history(
        self, check_id: str, limit: int = 20
    ) -> list[tuple[CheckResultRow, RunRow]]:
        with Session(self.engine) as session:
            statement = (
                select(CheckResultRow, RunRow)
                .join(RunRow, CheckResultRow.run_id == RunRow.id)
                .where(CheckResultRow.check_id == check_id)
                .order_by(RunRow.started_at.desc())
                .limit(limit)
            )
            return [(result, run) for result, run in session.execute(statement)]


def store_sink(url: str, project_root: Path) -> ResultSink:
    """A sink that records each run it receives in the store at `url`.

    The store is opened only when a run arrives, so a run that is never
    recorded never touches it — not even to create its directory.
    """

    def record(run: RunResult) -> None:
        with ResultStore.open(url, project_root) as store:
            store.save(run)

    return record
