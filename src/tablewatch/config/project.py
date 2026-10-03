"""Models for `tablewatch.yml`.

String settings may reference the environment as `${env:NAME}`. References
are resolved only at the moment of use — a connection being opened, a
notification being sent (`resolve_env`) — so `validate`, `list` and
`compile` work on a machine with no credentials.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ENV_REFERENCE = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")

PROJECT_FILE = "tablewatch.yml"


class MissingEnvironmentVariableError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"environment variable {name} is not set")
        self.name = name


def resolve_env(value: str) -> str:
    """Substitute every `${env:NAME}` in `value`; unset variables are errors."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise MissingEnvironmentVariableError(name)
        return os.environ[name]

    return ENV_REFERENCE.sub(substitute, value)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _DatasourceBase(_Strict):
    # How to read timestamps that carry no zone (see metrics/builtin/freshness.py).
    timezone: str = "UTC"


class PostgresDatasource(_DatasourceBase):
    type: Literal["postgres"]
    host: str
    port: int | str = 5432
    database: str
    user: str | None = None
    password: str | None = None
    # Extra libpq parameters, e.g. {sslmode: require}.
    options: dict[str, str] = Field(default_factory=dict)


class DuckDBDatasource(_DatasourceBase):
    type: Literal["duckdb"]
    path: str = ":memory:"
    read_only: bool = True


class SQLiteDatasource(_DatasourceBase):
    type: Literal["sqlite"]
    path: str


class URLDatasource(_DatasourceBase):
    """Any SQLAlchemy URL — the escape hatch for dialects without a type yet."""

    type: Literal["sqlalchemy"]
    url: str


class FilesDatasource(_DatasourceBase):
    """CSV, Parquet and JSON files under `root`, read in place by DuckDB."""

    type: Literal["files"]
    # Relative to the project, inside it. Not a secret, so not `${env:}`:
    # `validate` must be able to say where it points.
    root: str

    @field_validator("root")
    @classmethod
    def _inside_the_project(cls, value: str) -> str:
        if ENV_REFERENCE.search(value):
            raise ValueError(
                "a files root is a path in the project, not an ${env:} reference"
            )
        path = PurePosixPath(value.replace("\\", "/"))
        parts = [p for p in path.parts if p not in ("", ".")]
        if path.is_absolute() or ".." in path.parts or not parts:
            raise ValueError(
                "a files root must be a folder inside the project (not the project "
                f"itself), without '..'; got '{value}'"
            )
        if parts[0] == ".tablewatch":
            # Check SQL could read the results store and any secret beside it.
            raise ValueError("a files root cannot be the results folder .tablewatch")
        return value


Datasource = Annotated[
    PostgresDatasource
    | DuckDBDatasource
    | SQLiteDatasource
    | URLDatasource
    | FilesDatasource,
    Field(discriminator="type"),
]


class _URLNotifier(_Strict):
    # A webhook URL is a bearer secret, so it may only come from the
    # environment: a literal in YAML would end up in git.
    url: str

    @field_validator("url")
    @classmethod
    def _env_only(cls, value: str) -> str:
        if not ENV_REFERENCE.fullmatch(value):
            raise ValueError(
                "a notifier url must be an ${env:NAME} reference — it is a secret"
            )
        return value


class WebhookNotifier(_URLNotifier):
    """POSTs each run's state changes as JSON (`tablewatch.notify.payload`)."""

    type: Literal["webhook"]


class SlackNotifier(_URLNotifier):
    """Posts each run's state changes to a Slack incoming webhook."""

    type: Literal["slack"]


NotifierConfig = Annotated[WebhookNotifier | SlackNotifier, Field(discriminator="type")]
NOTIFIER_TYPES = ("webhook", "slack")


class ResultsConfig(_Strict):
    # Relative SQLite paths resolve against the project root, not the cwd,
    # so a cron job run from / writes to the same store as a developer.
    url: str = "sqlite:///.tablewatch/results.db"


class ProjectConfig(_Strict):
    name: str
    checks_path: str = "checks"
    datasources: dict[str, Datasource] = Field(default_factory=dict)
    results: ResultsConfig = Field(default_factory=ResultsConfig)
    notifiers: dict[str, NotifierConfig] = Field(default_factory=dict)
