"""Postgres for the results-store tests (spec 031): one switch, one schema per test.

Set `TABLEWATCH_TEST_POSTGRES_URL` to a SQLAlchemy URL for a Postgres server
whose role may create schemas and roles, for example::

    TABLEWATCH_TEST_POSTGRES_URL='postgresql+psycopg://tw:pw@127.0.0.1:5432/tw?connect_timeout=5' \\
        uv run pytest tests/test_results.py tests/test_results_postgres.py

Unset, every Postgres test is skipped with one reason. With
`TABLEWATCH_TEST_POSTGRES_REQUIRED=1` (CI), an unset, malformed or
unreachable URL ends the session instead: a required backend that is
silently skipped proves nothing.

Every message names the variable, never its value or the driver's text:
the URL holds a password, and the driver's text can repeat it.

Each test gets its own schema, `tw_<hex>`, reached through the URL's
`options=-c search_path=…`, and dropped at teardown once the test has
closed its stores. Roles a test creates are dropped with it.
"""

from __future__ import annotations

import os
import queue
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.pool import NullPool

URL_VARIABLE = "TABLEWATCH_TEST_POSTGRES_URL"
REQUIRED_VARIABLE = "TABLEWATCH_TEST_POSTGRES_REQUIRED"
NOT_SET = f"{URL_VARIABLE} not set"

# A password with every character that needs escaping in a URL, and a space
# (security R2). It also carries P14's sentinel, which no output may contain.
SENTINEL = "s3cr3t-031"
AWKWARD_PASSWORD = f"{SENTINEL} p@ss:w/rd%#?"

# How long teardown waits for a lock on the test schema before deciding a
# connection was left open.
_TEARDOWN_LOCK_TIMEOUT = "10s"


@dataclass(frozen=True)
class Verdict:
    """What the switch says: a server to use, why not, and whether to stop."""

    url: URL | None
    skip_reason: str
    problem: str | None  # set: end the session with it


class _Session:
    # Set once, by `check_server`, before any test runs.
    verdict = Verdict(None, NOT_SET, None)


def examine(environ: Mapping[str, str]) -> Verdict:
    """Read the switch from `environ`, connecting once if a URL is set."""
    raw = environ.get(URL_VARIABLE, "").strip()
    required = environ.get(REQUIRED_VARIABLE, "").strip() not in ("", "0")
    if not raw:
        problem = f"{REQUIRED_VARIABLE} is set but {URL_VARIABLE} is not"
        return Verdict(None, NOT_SET, problem if required else None)
    url, reason = _probe(raw)
    if url is not None:
        return Verdict(url, "", None)
    return Verdict(None, reason, reason if required else None)


def check_server() -> str | None:
    """Read the switch once per session; the reason to end it, or None.

    Called from `pytest_sessionstart`; the fixtures below use the result.
    """
    _Session.verdict = examine(os.environ)
    return _Session.verdict.problem


def _probe(raw: str) -> tuple[URL | None, str]:
    # Every failure is reduced to fixed words naming the variable; the
    # exception is dropped, so no traceback can carry the URL.
    try:
        url = make_url(raw)
    except Exception:
        return None, f"{URL_VARIABLE} is not a database URL"
    if url.get_backend_name() != "postgresql":
        return None, f"{URL_VARIABLE} is not a Postgres URL"
    if "connect_timeout" not in url.query:
        url = url.update_query_dict({"connect_timeout": "10"})
    try:
        engine = create_engine(url, poolclass=NullPool)
    except Exception:
        return None, f"{URL_VARIABLE} names a driver that is not installed"
    try:
        with engine.connect() as connection:
            allowed = connection.execute(
                text(
                    "SELECT rolsuper OR rolcreaterole FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).scalar()
    except Exception:
        return None, f"{URL_VARIABLE} is set, but its server could not be reached"
    finally:
        engine.dispose()
    if not allowed:
        return None, f"the role in {URL_VARIABLE} cannot create roles"
    return url, ""


def server_url() -> URL:
    """The configured server's URL, or skip the calling test."""
    verdict = _Session.verdict
    if verdict.url is None:
        pytest.skip(verdict.skip_reason)
    return verdict.url


def options(**settings: str) -> str:
    """A libpq `options` value setting each server parameter for the session.

    `options(search_path="tw_1", timezone="Asia/Singapore")` is
    `-c search_path=tw_1 -c timezone=Asia/Singapore`. Values must not hold a
    space (libpq would need a backslash before it); none used here do.
    """
    for name, value in settings.items():
        if " " in value or " " in name:
            raise ValueError(f"options: {name} cannot hold a space")
    return " ".join(f"-c {name}={value}" for name, value in settings.items())


@dataclass(frozen=True)
class Role:
    name: str
    password: str


@dataclass
class PgSchema:
    """One test's schema on the test server, and the roles made for it."""

    server: URL
    name: str
    admin: Engine
    roles: list[str] = field(default_factory=list)

    @property
    def application_name(self) -> str:
        # Every connection a test makes says which test schema it is for, so
        # teardown can find one left open.
        return self.name

    def url_object(
        self,
        *,
        role: Role | None = None,
        **settings: str,
    ) -> URL:
        """This schema's URL as an object, as `role` if given.

        `settings` are extra server parameters (`timezone="Asia/Singapore"`).
        """
        url = self.server.update_query_dict(
            {
                "application_name": self.application_name,
                "options": options(search_path=self.name, **settings),
            }
        )
        if role is not None:
            url = url.set(username=role.name, password=role.password)
        return url

    def url(self, *, role: Role | None = None, **settings: str) -> str:
        """This schema's URL as `results.url` takes it, password included."""
        return self.url_object(role=role, **settings).render_as_string(
            hide_password=False
        )

    def url_with_env_password(self, role: Role, variable: str) -> str:
        """This schema's URL for `role`, its password a `${env:variable}`
        reference, as a user writes it in `tablewatch.yml`."""
        return with_env_password(self.url_object(role=role), variable)

    def make_role(self, password: str = AWKWARD_PASSWORD) -> Role:
        """A login role that may create and write tables in this schema."""
        role = self._create_role(password)
        with self.admin.connect() as connection:
            connection.execute(
                text(f'GRANT USAGE, CREATE ON SCHEMA "{self.name}" TO "{role.name}"')
            )
        return role

    def make_reader(self, password: str = AWKWARD_PASSWORD) -> Role:
        """A login role with only SELECT on the tables now in this schema
        (P19, the README's reader): make it after the store is at head."""
        return self._granted(password, "SELECT ON ALL TABLES")

    def make_writer(self, password: str = AWKWARD_PASSWORD) -> Role:
        """The README's writer: SELECT and INSERT on the tables now in this
        schema, and the sequence behind the results' ids. No DDL."""
        return self._granted(
            password, "SELECT, INSERT ON ALL TABLES", "USAGE ON ALL SEQUENCES"
        )

    def _granted(self, password: str, *grants: str) -> Role:
        role = self._create_role(password)
        with self.admin.connect() as connection:
            connection.execute(
                text(f'GRANT USAGE ON SCHEMA "{self.name}" TO "{role.name}"')
            )
            for grant in grants:
                # `grant` is "<privileges> ON ALL <kind>"
                connection.execute(
                    text(f'GRANT {grant} IN SCHEMA "{self.name}" TO "{role.name}"')
                )
        return role

    def _create_role(self, password: str) -> Role:
        name = f"{self.name}_r{len(self.roles)}"
        with self.admin.connect() as connection:
            # A role's password cannot be a bind parameter; quote it as a
            # literal the way Postgres does, by doubling single quotes.
            quoted = password.replace("'", "''")
            connection.execute(
                text(f"CREATE ROLE \"{name}\" LOGIN PASSWORD '{quoted}'")
            )
        self.roles.append(name)
        return Role(name, password)

    def execute(self, sql: str, **params: Any) -> list[tuple[Any, ...]]:
        """Run `sql` in this schema as the admin role; rows if it returns any."""
        with self.admin.connect() as connection:
            connection.execute(text(f'SET search_path TO "{self.name}"'))
            result = connection.execute(text(sql), params)
            return [tuple(row) for row in result] if result.returns_rows else []

    def drop(self) -> None:
        """Drop the schema and its roles; fail if a connection was left open."""
        leaked = 0
        with self.admin.connect() as connection:
            connection.execute(text(f"SET lock_timeout = '{_TEARDOWN_LOCK_TIMEOUT}'"))
            leaked = len(
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE application_name = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": self.application_name},
                ).all()
            )
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{self.name}" CASCADE'))
            for role in reversed(self.roles):
                connection.execute(text(f'DROP OWNED BY "{role}"'))
                connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        assert not leaked, (
            f"{leaked} connection(s) to the test schema were left open: "
            "a store or engine was not closed"
        )


def with_env_password(url: URL, variable: str) -> str:
    """`url` written out with its password replaced by `${env:variable}`."""
    marker = "PASSWORDMARKER031"
    rendered = url.set(password=marker).render_as_string(hide_password=False)
    assert rendered.count(marker) == 1
    return rendered.replace(marker, "${env:" + variable + "}")


@pytest.fixture(scope="session")
def pg_admin() -> Iterator[Engine]:
    """An autocommit engine on the test server, as the URL's own role."""
    url = server_url()
    engine = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pg_schema(pg_admin: Engine) -> Iterator[PgSchema]:
    """An empty schema for one test, dropped (with its roles) afterwards."""
    schema = PgSchema(server_url(), f"tw_{uuid.uuid4().hex}", pg_admin)
    with pg_admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema.name}"'))
    try:
        yield schema
    finally:
        schema.drop()


def sqlite_url(directory: Path) -> str:
    return f"sqlite:///{directory / 'results.db'}"


# --- worker processes (multiprocessing "spawn": importable, picklable) --------


def open_after_barrier(barrier: Any, url: str, root: str, out: Any) -> None:
    """P6: wait for every worker, then open (and so migrate) the store."""
    from tablewatch.results.store import open_store

    barrier.wait(timeout=60)
    try:
        with open_store(url, Path(root)):
            pass
    except Exception as exc:
        out.put(f"{type(exc).__name__}: {exc}")
    else:
        out.put("ok")


def run_repeatedly(barrier: Any, root: str, times: int, out: Any) -> None:
    """P7: run a project `times` times, meeting the other worker before each."""
    import tablewatch as tw

    for _ in range(times):
        barrier.wait(timeout=120)
        try:
            run = tw.run(root, notify=False)
        except Exception as exc:
            out.put(("crashed", 0, [f"{type(exc).__name__}: {exc}"]))
            return
        out.put((run.id, len(run.results), list(run.record_errors)))


def collect(out: Any, count: int, timeout: float) -> list[Any]:
    """`count` items from a multiprocessing queue, or fail naming how many came."""
    items: list[Any] = []
    try:
        while len(items) < count:
            items.append(out.get(timeout=timeout))
    except queue.Empty:
        pytest.fail(f"workers reported {len(items)} of {count} results in time")
    return items
