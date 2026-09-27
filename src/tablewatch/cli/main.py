"""tablewatch CLI entry point.

Reachable as both `tablewatch` and the short `tw` — see `[project.scripts]`.

Built to run unattended: no prompts, logs on stderr (stdout stays clean for
`--output json`), and exit codes an orchestrator can act on:

    0  every selected check passed (warnings too, unless --fail-on warn)
    1  a check failed — the data is bad
    2  a check could not be evaluated — tablewatch could not do its job
    3  the project is invalid, or nothing matched — nothing ran

`serve` is a long-running command: it exits 0 when stopped by SIGINT or
SIGTERM, and 3 when it could not start. It never exits 1 or 2 itself.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import click
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from tablewatch import __version__, logs, templates
from tablewatch.api import default_sinks, execute
from tablewatch.checks.model import Check, Dataset
from tablewatch.config import Project, find_project_root, load_project
from tablewatch.config.jsonschema import check_file_schema, project_schema
from tablewatch.config.project import PROJECT_FILE, MissingEnvironmentVariableError
from tablewatch.datasources import DatasourceError, create_engine_for
from tablewatch.diagnostics import ProjectError, Severity
from tablewatch.engine.compiled import compile_dataset
from tablewatch.engine.executor import error_message
from tablewatch.engine.runner import FAIL_ON_CHOICES, MAX_CONCURRENCY, FailOn
from tablewatch.output import REPORTERS, console
from tablewatch.results import ResultStore
from tablewatch.selection import Selection, SelectionError, select_checks

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_CHECK_ERROR = 2
EXIT_INVALID_PROJECT = 3

log = logging.getLogger("tablewatch.cli")


@dataclass
class _Settings:
    project_dir: Path | None
    quiet: bool


@click.group()
@click.version_option(version=__version__, prog_name="tablewatch")
@click.option(
    "--project-dir",
    type=click.Path(file_okay=False, path_type=Path),
    envvar="TABLEWATCH_PROJECT_DIR",
    help="Project root. Default: the nearest directory with a tablewatch.yml.",
)
@click.option(
    "--log-format",
    type=click.Choice(["text", "json"]),
    default="text",
    envvar="TABLEWATCH_LOG_FORMAT",
    show_default=True,
    help="How log lines on stderr are written.",
)
@click.option("-v", "--verbose", count=True, help="More logging; repeat for debug.")
@click.option(
    "-q", "--quiet", is_flag=True, help="Errors only; a one-line run summary."
)
@click.pass_context
def cli(
    ctx: click.Context,
    project_dir: Path | None,
    log_format: str,
    verbose: int,
    quiet: bool,
) -> None:
    """Data quality checks for your tables."""
    level = (
        logging.ERROR
        if quiet
        else [logging.WARNING, logging.INFO, logging.DEBUG][min(verbose, 2)]
    )
    logs.configure(level, log_format)
    ctx.obj = _Settings(project_dir=project_dir, quiet=quiet)


# --- shared helpers -----------------------------------------------------------


def _fail(message: str, code: int = EXIT_INVALID_PROJECT) -> NoReturn:
    click.echo(f"tablewatch: {message}", err=True)
    sys.exit(code)


def _project(ctx: click.Context, require_valid: bool = True) -> Project:
    settings: _Settings = ctx.obj
    root = settings.project_dir or find_project_root(Path.cwd())
    if root is None:
        _fail(
            f"no {PROJECT_FILE} here or in any parent directory — run `tablewatch init`"
        )
    try:
        project = load_project(root)
    except ProjectError as exc:
        for diagnostic in exc.diagnostics:
            click.echo(str(diagnostic), err=True)
        sys.exit(EXIT_INVALID_PROJECT)
    for diagnostic in project.diagnostics:
        if require_valid or diagnostic.severity is Severity.WARNING:
            click.echo(str(diagnostic), err=True)
    if require_valid and not project.ok:
        errors = sum(1 for d in project.diagnostics if d.severity is Severity.ERROR)
        _fail(
            f"{errors} error{'s' if errors != 1 else ''} in the project — nothing ran"
        )
    return project


def _selector_options[F: Callable[..., Any]](command: F) -> F:
    options: list[Callable[[F], F]] = [
        click.argument("paths", nargs=-1),
        click.option(
            "--tag", "tags", multiple=True, help="Only datasets with this tag."
        ),
        click.option(
            "--datasource", "datasources", multiple=True, help="Only this datasource."
        ),
        click.option(
            "--exclude", "excludes", multiple=True, help="Skip a path or glob."
        ),
        click.option(
            "--check",
            "check_ids",
            multiple=True,
            help="Only this check id (or prefix).",
        ),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def _select(
    project: Project, **selectors: tuple[str, ...]
) -> tuple[Selection, list[Check]]:
    selection = Selection(**selectors)
    try:
        return selection, select_checks(project, selection)
    except SelectionError as exc:
        _fail(str(exc))


# --- commands -------------------------------------------------------------------


@cli.command()
@click.argument(
    "directory", type=click.Path(file_okay=False, path_type=Path), default="."
)
@click.option("--name", help="Project name. Default: the directory's name.")
def init(directory: Path, name: str | None) -> None:
    """Create a project: config, an example check, editor schemas."""
    directory = directory.resolve()
    if (directory / PROJECT_FILE).exists():
        _fail(f"{directory / PROJECT_FILE} already exists")
    files = {
        PROJECT_FILE: templates.TABLEWATCH_YML.format(name=name or directory.name),
        "checks/_defaults.yml": templates.DEFAULTS_YML,
        "checks/example/orders.yml": templates.EXAMPLE_CHECKS_YML,
        "schemas/check-file.schema.json": json.dumps(check_file_schema(), indent=2)
        + "\n",
        "schemas/tablewatch.schema.json": json.dumps(project_schema(), indent=2) + "\n",
        ".gitignore": templates.GITIGNORE,
        ".vscode/settings.json": templates.VSCODE_SETTINGS,
    }
    for relative, content in files.items():
        path = directory / relative
        if path.exists():
            click.echo(f"  kept     {relative} (already exists)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        click.echo(f"  created  {relative}")
    click.echo(
        f"\nProject ready in {directory}. Next: edit {PROJECT_FILE}, then `tablewatch validate`."
    )


@cli.command()
@click.pass_context
def validate(ctx: click.Context) -> None:
    """Check every file for mistakes. Needs no database or credentials."""
    project = _project(ctx, require_valid=False)
    errors = [d for d in project.diagnostics if d.severity is Severity.ERROR]
    for diagnostic in errors:
        click.echo(str(diagnostic), err=True)
    checks = len(project.checks)
    summary = f"{len(project.datasets)} datasets, {checks} checks"
    if errors:
        _fail(f"{summary} — {len(errors)} error{'s' if len(errors) != 1 else ''}")
    warnings = sum(1 for d in project.diagnostics if d.severity is Severity.WARNING)
    if warnings:
        # A warning can mean a check that never checked: the closing line is
        # the one people read in a CI log.
        click.echo(
            f"{summary} — no errors, {warnings} warning{'s' if warnings != 1 else ''}"
        )
        return
    click.echo(f"{summary} — no problems found")


@cli.command("list")
@_selector_options
@click.option(
    "--output", type=click.Choice(["table", "json"]), default="table", show_default=True
)
@click.pass_context
def list_checks(
    ctx: click.Context, /, output: str, **selectors: tuple[str, ...]
) -> None:
    """Show checks after inheritance, with their ids and sources."""
    project = _project(ctx)
    _, checks = _select(project, **selectors)
    if output == "json":
        click.echo(
            json.dumps(
                [
                    {
                        "id": c.id,
                        "name": c.name,
                        "expression": c.canonical,
                        "dataset": c.dataset.name,
                        "datasource": c.dataset.datasource,
                        "owner": c.dataset.owner,
                        "tags": list(c.dataset.tags),
                        "source": str(c.location),
                    }
                    for c in checks
                ],
                indent=2,
            )
        )
        return
    rows = [
        (c.short_id, c.dataset.name, c.dataset.datasource, c.name, str(c.location))
        for c in checks
    ]
    _table(("ID", "DATASET", "DATASOURCE", "CHECK", "SOURCE"), rows)
    click.echo(f"\n{len(checks)} checks")


@cli.command()
@_selector_options
@click.pass_context
def compile(ctx: click.Context, /, **selectors: tuple[str, ...]) -> None:  # noqa: A001
    """Print the SQL each dataset will run, without running it."""
    from datetime import UTC, datetime

    project = _project(ctx)
    _, checks = _select(project, **selectors)
    now = datetime.now(UTC)
    by_dataset: dict[int, list[Check]] = {}
    datasets: dict[int, Dataset] = {}
    for check in checks:
        by_dataset.setdefault(id(check.dataset), []).append(check)
        datasets[id(check.dataset)] = check.dataset
    for key, dataset_checks in by_dataset.items():
        dataset = datasets[key]
        click.echo(
            f"-- {dataset.name} on {dataset.datasource} ({dataset.path.as_posix()})"
        )
        compiled = compile_dataset(
            dataset, project.config.datasources, dataset_checks, now=now
        )
        if compiled.error is not None:
            click.echo(f"-- cannot compile: {compiled.error}\n")
            continue
        if compiled.scan is not None:
            click.echo(f"-- single scan: {len(compiled.scan.columns)} measures")
            click.echo(compiled.scan.sql + ";")
        for query in compiled.queries:
            click.echo(query.sql + ";")
        if compiled.schema_lookup:
            click.echo(f"-- plus a schema lookup of {dataset.table}")
        click.echo()


@cli.command()
@_selector_options
@click.option(
    "--fail-on",
    type=click.Choice(FAIL_ON_CHOICES),
    default="fail",
    show_default=True,
    help="Lowest outcome that makes the exit code non-zero.",
)
@click.option(
    "--output",
    type=click.Choice(sorted(REPORTERS)),
    default="table",
    show_default=True,
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write the report here instead of stdout.",
)
@click.option(
    "--no-store", is_flag=True, help="Do not record this run in the results store."
)
@click.option(
    "--concurrency",
    type=click.IntRange(1, MAX_CONCURRENCY),
    default=4,
    show_default=True,
)
@click.pass_context
def run(
    ctx: click.Context,
    /,
    fail_on: str,
    output: str,
    output_file: Path | None,
    no_store: bool,
    concurrency: int,
    **selectors: tuple[str, ...],
) -> None:
    """Run checks and record the results."""
    settings: _Settings = ctx.obj
    project = _project(ctx)
    try:
        result = execute(
            project,
            Selection(**selectors),
            sinks=default_sinks(project, record=not no_store),
            fail_on=cast(FailOn, fail_on),
            concurrency=concurrency,
            trigger="cli",
            cwd=Path.cwd(),
        )
    except SelectionError as exc:
        _fail(str(exc))
    # The checks ran and their outcome stands, but a gap in history is
    # tablewatch failing at part of its job: exit 2 (see RunResult.exit_code).
    for reason in result.record_errors:
        click.echo(f"tablewatch: could not record the run: {reason}", err=True)
    code = result.exit_code()

    if output == "table" and output_file is None:
        if settings.quiet:
            click.echo(console.summary(result))
        else:
            click.echo(console.render(result, colour=sys.stdout.isatty()))
    else:
        report = REPORTERS[output](result)
        if output_file is None:
            click.echo(report)
        else:
            output_file.write_text(report + "\n", encoding="utf-8")
            click.echo(console.summary(result))
    sys.exit(code)


SERVER_PACKAGES = frozenset({"fastapi", "starlette", "uvicorn"})


@cli.command()
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Address to listen on. Anything but loopback serves check files, SQL "
    "and results without authentication.",
)
@click.option("--port", type=click.IntRange(0, 65535), default=8765, show_default=True)
@click.option(
    "--allowed-host",
    "allowed_hosts",
    multiple=True,
    help="A host name clients may use to reach the server (repeatable). "
    "IP addresses and localhost are always accepted.",
)
@click.pass_context
def serve(
    ctx: click.Context, host: str, port: int, allowed_hosts: tuple[str, ...]
) -> None:
    """Serve the project's checks and results as a read-only JSON API."""
    from datetime import UTC, datetime

    from tablewatch.results.store import StoreError, is_persistent, open_store
    from tablewatch.server.hosts import is_loopback

    try:
        from tablewatch.server import serve as server
        from tablewatch.server.app import create_app
        from tablewatch.server.routes import ServerContext
        from tablewatch.server.ui import load_bundle
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in SERVER_PACKAGES:
            raise
        _fail(
            "tablewatch serve needs the server extra: pip install 'tablewatch[server]'"
        )

    settings: _Settings = ctx.obj
    project = _project(ctx, require_valid=False)
    errors = [d for d in project.diagnostics if d.severity is Severity.ERROR]
    for diagnostic in errors:
        click.echo(str(diagnostic), err=True)
    if errors:
        click.echo(
            f"tablewatch: {len(errors)} error{'s' if len(errors) != 1 else ''} in the "
            f"project — serving the {len(project.checks)} checks that loaded",
            err=True,
        )

    try:
        if not is_persistent(project.config.results.url):
            _fail("serve needs a results store on disk, not an in-memory database")
        store = open_store(project.config.results.url, project.root)
    except StoreError as exc:
        log.info("%s", exc)  # driver detail can name hosts and users: not by default
        _fail("results store: could not be opened — run with -v for details")

    with store:
        try:
            sock = server.bind(host, port)
        except OSError as exc:
            _fail(f"could not listen on {host}:{port}: {exc.strerror or exc}")
        if not is_loopback(host):
            click.echo(
                f"tablewatch: warning: serving on {host} with no authentication — anyone "
                "who can reach this address can read this project's check files "
                "(comments included), the SQL each check runs, and its results: data "
                "values, database error messages that can quote row values, and owner "
                "emails. Authentication arrives in Phase 4 (tablewatch.yml cannot turn "
                "it on yet).",
                err=True,
            )
        shown = f"[{host}]" if ":" in host else host
        started = (
            f"tablewatch serve: http://{shown}:{sock.getsockname()[1]}/ "
            f"(project {project.config.name}, {len(project.checks)} checks; "
            "API at /api/v1)"
        )
        context = ServerContext(
            project=project, store=store, loaded_at=datetime.now(UTC)
        )
        bundle = load_bundle()
        if bundle is None:
            click.echo(
                "tablewatch: warning: web UI not found in this installation — "
                "serving the API only",
                err=True,
            )
        app = create_app(context, allowed_hosts=allowed_hosts, ui=bundle)
        server.run(
            app,
            sock,
            access_log=not settings.quiet,
            on_ready=lambda: click.echo(started, err=True),
        )


@cli.command("test-connection")
@click.argument("names", nargs=-1)
@click.pass_context
def test_connection(ctx: click.Context, names: tuple[str, ...]) -> None:
    """Connect to each datasource (default: all) and run SELECT 1."""
    project = _project(ctx, require_valid=False)
    configured = project.config.datasources
    unknown = [n for n in names if n not in configured]
    if unknown:
        _fail(f"unknown datasource: {', '.join(unknown)}")
    failed = 0
    for name in names or tuple(configured):
        try:
            engine = create_engine_for(configured[name], project.root)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            click.echo(f"ok      {name}")
        except (DatasourceError, MissingEnvironmentVariableError) as exc:
            failed += 1
            click.echo(f"FAILED  {name}: {exc}")
        except SQLAlchemyError as exc:
            failed += 1
            click.echo(f"FAILED  {name}: {error_message(exc)}")
    sys.exit(EXIT_CHECK_ERROR if failed else EXIT_OK)


@cli.command()
@click.option("--limit", type=click.IntRange(1, 1000), default=20, show_default=True)
@click.pass_context
def runs(ctx: click.Context, limit: int) -> None:
    """Recent runs from the results store."""
    project = _project(ctx, require_valid=False)
    with ResultStore.open(project.config.results.url, project.root) as store:
        recent = store.recent_runs(limit)
    rows = [
        (
            r.id[:12],
            _when(r.started_at),
            r.outcome.upper(),
            str(r.total),
            f"{r.passed}/{r.warned}/{r.failed}/{r.errored}",
            str(r.exit_code),
            r.hostname,
        )
        for r in recent
    ]
    if not rows:
        click.echo("no runs recorded yet")
        return
    _table(
        ("RUN", "STARTED (UTC)", "OUTCOME", "CHECKS", "P/W/F/E", "EXIT", "HOST"), rows
    )


@cli.command()
@click.argument("check_id")
@click.option("--limit", type=click.IntRange(1, 1000), default=20, show_default=True)
@click.pass_context
def history(ctx: click.Context, check_id: str, limit: int) -> None:
    """Outcomes and values of one check over its recent runs."""
    project = _project(ctx, require_valid=False)
    with ResultStore.open(project.config.results.url, project.root) as store:
        matches = store.matching_check_ids(check_id)
        entries = store.history(matches[0], limit) if len(matches) == 1 else []
    if not matches:
        _fail(f"no recorded results for check {check_id}")
    if len(matches) > 1:
        _fail(f"{check_id} is ambiguous: {', '.join(m[:12] for m in matches)}")
    latest = entries[0][0]
    click.echo(f"{latest.check_name}  [{latest.dataset}]  {latest.source}\n")
    _table(
        ("STARTED (UTC)", "OUTCOME", "VALUE", "DETAIL", "RUN"),
        [
            (
                _when(run.started_at),
                r.outcome.upper(),
                r.display_value,
                r.message or "",
                run.id[:12],
            )
            for r, run in entries
        ],
    )


@cli.command()
@click.option(
    "--kind",
    type=click.Choice(["checks", "project"]),
    default="checks",
    show_default=True,
    help="Schema for check files, or for tablewatch.yml.",
)
def schema(kind: str) -> None:
    """Print a JSON Schema for editor completion and validation."""
    document = check_file_schema() if kind == "checks" else project_schema()
    click.echo(json.dumps(document, indent=2))


# --- formatting -------------------------------------------------------------------


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    widths = [
        max([len(h), *(len(row[i]) for row in rows)]) for i, h in enumerate(headers)
    ]
    for line in (headers, *rows):
        click.echo(
            "  ".join(
                cell.ljust(w) for cell, w in zip(line, widths, strict=True)
            ).rstrip()
        )


def _when(moment: object) -> str:
    return (
        moment.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(moment, "strftime")
        else str(moment)
    )


if __name__ == "__main__":  # pragma: no cover
    cli()
