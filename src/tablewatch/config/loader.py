"""Turn a project directory into resolved datasets and checks.

Loading never stops at the first problem. Every file is read and every
problem is collected as a `Diagnostic`, so one `tablewatch validate` reports
everything that is wrong, each at its `file:line:col`.
"""

from __future__ import annotations

import difflib
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.nodes import MappingNode

from tablewatch.checks.model import (
    DATASOURCE_NAME,
    Check,
    Dataset,
    DatasourceState,
    SourceSpan,
    canonical_text,
    derive_check_id,
)
from tablewatch.checks.sources import FileSource, file_format
from tablewatch.config.project import (
    NOTIFIER_TYPES,
    PROJECT_FILE,
    FilesDatasource,
    ProjectConfig,
)
from tablewatch.config.spans import check_span, compose, split_lines
from tablewatch.config.yamlsource import YAMLSource, plain, quote_offset
from tablewatch.diagnostics import (
    Diagnostic,
    ProjectError,
    SourceLocation,
    error,
    has_errors,
    warning,
)
from tablewatch.dsl import (
    Condition,
    DSLSyntaxError,
    Duration,
    parse_check,
    parse_trigger,
)
from tablewatch.dsl.ast import Number, values_in
from tablewatch.metrics.base import SINGLE_VALUES, Metric, OptionType, Unit
from tablewatch.metrics.registry import get_metric
from tablewatch.metrics.registry import suggest as suggest_metric

log = logging.getLogger(__name__)

DEFAULTS_FILES = frozenset({"_defaults.yml", "_defaults.yaml"})
CHECK_FILE_SUFFIXES = frozenset({".yml", ".yaml"})

DATASET_KEYS = ("dataset", "datasource", "filter", "owner", "tags", "notify", "checks")
DEFAULTS_KEYS = ("datasource", "owner", "tags", "notify")
COMMON_CHECK_KEYS = ("name", "id", "warn", "fail", "notify")
# Notifier names: echoed in diagnostics and on stderr, so nothing that could
# be a URL or a secret. `owner` is kept for routing to a check's owner (I-11).
NOTIFIER_NAME = DATASOURCE_NAME
RESERVED_NOTIFIER = "owner"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
# The results store's check_id column is this wide.
MAX_ID_LENGTH = 64


@dataclass
class Project:
    """A loaded project: its config, datasets and checks, and any diagnostics.

    Public: `root`, `datasets`, `checks`, `diagnostics`, `ok`. `config` is
    provisional and may change between releases.
    """

    root: Path
    config: ProjectConfig
    datasets: list[Dataset] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # Where each datasource is defined in tablewatch.yml (provisional).
    datasource_locations: dict[str, SourceLocation] = field(default_factory=dict)

    @property
    def checks(self) -> list[Check]:
        return [check for dataset in self.datasets for check in dataset.checks]

    @property
    def ok(self) -> bool:
        return not has_errors(self.diagnostics)

    @property
    def checks_dir(self) -> Path:
        return self.root / self.config.checks_path


def find_project_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` holding a `tablewatch.yml`."""
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / PROJECT_FILE).is_file():
            return directory
    return None


def find_project(project_dir: Path | None = None) -> Path:
    """The project root: `project_dir` (a directory or its `tablewatch.yml`),
    else the nearest directory at or above the cwd holding a `tablewatch.yml`.

    The one way the CLI and `tablewatch.load()` find a project. Raises
    `ProjectError` when there is none.
    """
    if project_dir is not None:
        if project_dir.is_file() and project_dir.name == PROJECT_FILE:
            return project_dir.parent
        return project_dir
    cwd = Path.cwd()
    root = find_project_root(cwd)
    if root is None:
        raise ProjectError(
            [
                error(
                    f"no {PROJECT_FILE} in {cwd} or any parent directory — "
                    'run "tablewatch init"'
                )
            ]
        )
    return root


def load_project(root: Path) -> Project:
    """Load config and every check file under `root`.

    Raises `ProjectError` only when `tablewatch.yml` itself is unusable.
    Problems in check files are returned on `Project.diagnostics`.
    """
    root = root.resolve()
    config, locations = _load_config(root)
    project = Project(root=root, config=config, datasource_locations=locations)
    _ChecksLoader(project).load()
    return project


# --- tablewatch.yml ---------------------------------------------------------


def _load_config(root: Path) -> tuple[ProjectConfig, dict[str, SourceLocation]]:
    path = root / PROJECT_FILE
    if not path.is_file():
        raise ProjectError([error(f"no {PROJECT_FILE} in {root}")])
    source = YAMLSource(path, Path(PROJECT_FILE))
    node, diagnostics = source.load()
    if diagnostics:
        raise ProjectError(diagnostics)
    if not isinstance(node, CommentedMap):
        raise ProjectError(
            [error(f"{PROJECT_FILE} must be a mapping", source.at(0, 0))]
        )
    try:
        config = ProjectConfig.model_validate(plain(node))
    except ValidationError as exc:
        raise ProjectError(
            [
                error(_describe_validation(e), source.locate(node, e["loc"]))
                for e in exc.errors()
            ]
        ) from None
    problems = [
        error(message, _key_at(source, node, name))
        for name, message in _notifier_name_problems(config)
    ]
    notifiers = node.get("notifiers")
    if isinstance(notifiers, CommentedMap):
        # YAML turns `null:` or `1:` into a key that is not text; pydantic
        # would quietly make it the name "None" or "1".
        problems.extend(
            error(_BAD_NOTIFIER_NAME, source.of_key(notifiers, key))
            for key in notifiers
            if not isinstance(key, str)
        )
    if problems:
        raise ProjectError(problems)
    sources = node.get("datasources")
    locations = (
        {str(name): source.of_key(sources, name) for name in sources}
        if isinstance(sources, CommentedMap)
        else {}
    )
    return config, locations


_BAD_NOTIFIER_NAME = (
    "a notifier name is letters, digits, '_', '.' or '-' (at most 64 characters)"
)


def _notifier_name_problems(config: ProjectConfig) -> list[tuple[str, str]]:
    """Names are echoed in diagnostics and warnings, so they must be plain."""
    problems = []
    for name in config.notifiers:
        if name == RESERVED_NOTIFIER:
            problems.append(
                (name, "'owner' is reserved for routing to a check's owner — rename it")
            )
        elif not NOTIFIER_NAME.fullmatch(name):
            problems.append((name, _BAD_NOTIFIER_NAME))
    return problems


def _key_at(source: YAMLSource, node: CommentedMap, name: str) -> SourceLocation:
    notifiers = node.get("notifiers")
    if isinstance(notifiers, CommentedMap) and name in notifiers:
        return source.of_key(notifiers, name)
    return source.locate(node, ("notifiers",))


def _describe_validation(err: Any) -> str:
    loc = [str(step) for step in err["loc"]]
    if (
        loc[:1] == ["notifiers"]
        and len(loc) > 1
        and not NOTIFIER_NAME.fullmatch(loc[1])
    ):
        # A name that is not plain may be a pasted URL: never echo it.
        loc[1] = "…"
    setting = loc[-1] if loc else "setting"
    match err["type"]:
        case "missing":
            return f"missing required setting '{setting}'"
        case "extra_forbidden":
            return f"unknown setting '{setting}'"
        case "union_tag_invalid" | "union_tag_not_found" if loc[:1] == ["notifiers"]:
            return f"notifier 'type' must be one of: {', '.join(NOTIFIER_TYPES)}"
        case "union_tag_invalid" | "union_tag_not_found":
            return (
                "datasource 'type' must be one of: postgres, duckdb, sqlite, sqlalchemy"
            )
        case "value_error":
            # Our own validators' messages, without pydantic's "Value error, ".
            return str(err["ctx"]["error"])
        case _:
            return f"{setting}: {err['msg']}"


# --- check files -------------------------------------------------------------


@dataclass(frozen=True)
class _Defaults:
    datasource: str | None = None
    owner: str | None = None
    tags: tuple[str, ...] = ()
    # None: not set here, inherit. (): set to nobody (`notify: []`).
    notify: tuple[str, ...] | None = None

    def overlaid_with(self, nearer: _Defaults) -> _Defaults:
        """`nearer` wins for single values and `notify`; tags accumulate."""
        return _Defaults(
            datasource=nearer.datasource or self.datasource,
            owner=nearer.owner or self.owner,
            tags=_union(self.tags, nearer.tags),
            notify=self.notify if nearer.notify is None else nearer.notify,
        )


def _union(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(tag for group in groups for tag in group))


class _ChecksLoader:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.diagnostics = project.diagnostics
        self._defaults_cache: dict[Path, _Defaults] = {}
        self._ids: dict[str, SourceLocation] = {}
        self._warned_lists: set[int] = set()

    def load(self) -> None:
        checks_dir = self.project.checks_dir
        if not checks_dir.is_dir():
            self.diagnostics.append(
                error(
                    f"checks directory '{self.project.config.checks_path}' does not exist"
                )
            )
            return
        for path in sorted(checks_dir.rglob("*")):
            if not self._is_check_file(path):
                continue
            dataset = self._load_dataset(path, self._defaults_for(path.parent))
            if dataset is not None:
                self.project.datasets.append(dataset)

    def _is_check_file(self, path: Path) -> bool:
        relative = path.relative_to(self.project.checks_dir)
        return (
            path.is_file()
            and path.suffix in CHECK_FILE_SUFFIXES
            and path.name not in DEFAULTS_FILES
            and not any(part.startswith(".") for part in relative.parts)
        )

    def _source(self, path: Path) -> YAMLSource:
        return YAMLSource(path, path.relative_to(self.project.root))

    # -- defaults --

    def _defaults_for(self, directory: Path) -> _Defaults:
        if directory in self._defaults_cache:
            return self._defaults_cache[directory]
        checks_dir = self.project.checks_dir
        inherited = (
            _Defaults()
            if directory == checks_dir
            else self._defaults_for(directory.parent)
        )
        own = next(
            (
                directory / name
                for name in sorted(DEFAULTS_FILES)
                if (directory / name).is_file()
            ),
            None,
        )
        result = inherited.overlaid_with(self._load_defaults(own)) if own else inherited
        self._defaults_cache[directory] = result
        return result

    def _load_defaults(self, path: Path) -> _Defaults:
        source = self._source(path)
        node, diagnostics = source.load()
        self.diagnostics.extend(diagnostics)
        if node is None:
            return _Defaults()
        if not isinstance(node, CommentedMap):
            self.diagnostics.append(
                error("_defaults must be a mapping", source.at(0, 0))
            )
            return _Defaults()
        self._reject_unknown(source, node, DEFAULTS_KEYS, "setting in _defaults")
        return _Defaults(
            datasource=self._string(source, node, "datasource"),
            owner=self._string(source, node, "owner"),
            tags=self._tags(source, node),
            notify=self._notify(source, node),
        )

    # -- datasets --

    def _load_dataset(self, path: Path, defaults: _Defaults) -> Dataset | None:
        source = self._source(path)
        node, diagnostics = source.load()
        self.diagnostics.extend(diagnostics)
        if diagnostics:
            return None
        if node is None:
            self.diagnostics.append(warning("empty check file", source.at(0, 0)))
            return None
        if not isinstance(node, CommentedMap):
            self.diagnostics.append(
                error(
                    "a check file is a mapping with `dataset:` and `checks:`",
                    source.at(0, 0),
                )
            )
            return None
        self._reject_unknown(source, node, DATASET_KEYS, "key")

        name = self._string(source, node, "dataset")
        if name is None:
            if "dataset" not in node:
                self.diagnostics.append(
                    error(
                        "missing `dataset:` — the table these checks run against",
                        source.at(0, 0),
                    )
                )
            return None

        datasource, state = self._resolve_datasource(source, node, defaults)
        file_source = None
        if state == "defined" and isinstance(
            self.project.config.datasources.get(datasource), FilesDatasource
        ):
            file_source = self._file_source(source, node, name)
            if file_source is None:
                return None
            name = file_source.path
        dataset = Dataset(
            name=name,
            source=file_source,
            datasource=datasource,
            datasource_state=state,
            path=source.relative,
            location=source.of_key(node, "dataset"),
            filter=self._string(source, node, "filter"),
            filter_line=_own_key_line(source, node, "filter"),
            source_lines=split_lines(source.text or ""),
            owner=self._string(source, node, "owner") or defaults.owner,
            tags=_union(defaults.tags, self._tags(source, node)),
        )
        own_notify = self._notify(source, node)
        dataset.notify = own_notify if own_notify is not None else defaults.notify or ()

        checks = node.get("checks")
        if checks is None:
            self.diagnostics.append(
                error("missing `checks:` list", source.of_key(node, "dataset"))
            )
        elif not isinstance(checks, CommentedSeq):
            self.diagnostics.append(
                error("`checks:` must be a list", source.of_value(node, "checks"))
            )
        else:
            if not checks:
                self.diagnostics.append(
                    warning("`checks:` is empty", source.of_key(node, "checks"))
                )
            root = _composed(source.text or "")
            for index in range(len(checks)):
                check = self._load_check(source, dataset, checks, index)
                if check is not None:
                    if root is not None:
                        check.span = _span(dataset.source_lines, root, index)
                    dataset.checks.append(check)
        return dataset

    def _file_source(
        self, source: YAMLSource, node: CommentedMap, name: str
    ) -> FileSource | None:
        """A files datasource's dataset: a local path or pattern inside its root.

        Normalised (`./orders.csv` is `orders.csv`) before it names the
        dataset, so the check id does not depend on how it was written, nor,
        for a pattern, on what it matches.
        """
        at = source.of_value(node, "dataset")
        if any(ord(c) < 32 or ord(c) == 127 for c in name):
            self.diagnostics.append(
                error("a files dataset path cannot hold control characters", at)
            )
            return None
        if set(name) & set("{}"):
            self.diagnostics.append(
                error(
                    "a files dataset pattern may use *, ?, [ ] and **; braces ({ }) "
                    f"are not supported; got '{name}'",
                    at,
                )
            )
            return None
        if "://" in name:
            self.diagnostics.append(
                error(
                    "files datasets are local paths; URLs are not supported; "
                    f"got '{name}'",
                    at,
                )
            )
            return None
        path = PurePosixPath(name.replace("\\", "/"))
        parts = [p for p in path.parts if p not in (".", "")]
        if path.is_absolute() or ".." in parts or not parts:
            self.diagnostics.append(
                error(
                    "a files dataset must be a path inside its datasource's root; "
                    f"got '{name}'",
                    at,
                )
            )
            return None
        relative = "/".join(parts)
        fmt = file_format(relative)
        if fmt is None:
            self.diagnostics.append(
                error(
                    f"cannot tell the format of '{relative}' from its extension: "
                    "use .csv, .tsv, .parquet, .json, .jsonl or .ndjson",
                    at,
                )
            )
            return None
        return FileSource(relative, fmt)

    def _resolve_datasource(
        self, source: YAMLSource, node: CommentedMap, defaults: _Defaults
    ) -> tuple[str, DatasourceState]:
        """The dataset's datasource and its state; the one place that decides.

        An undefined name is kept only if it is a name, so a URL pasted into
        `datasource:` is never shown back by the API or the page.
        """
        configured = self.project.config.datasources
        explicit = self._string(source, node, "datasource")
        if "datasource" in node and not isinstance(node["datasource"], str):
            # Written but not a string (diagnosed above): never fall back to
            # a default or the only datasource, and never show the value.
            return "", "not_a_name"
        name = explicit or defaults.datasource
        where = (
            source.of_value(node, "datasource")
            if explicit
            else source.of_key(node, "dataset")
        )
        if name is None:
            if len(configured) == 1:
                return next(iter(configured)), "defined"
            self.diagnostics.append(
                error(
                    "no datasource for this dataset — set `datasource:` here or in a _defaults.yml",
                    where,
                )
            )
            return "", "none"
        if name not in configured:
            known = ", ".join(sorted(configured)) or "none are defined"
            self.diagnostics.append(
                error(
                    f"unknown datasource '{name}' (defined in tablewatch.yml: {known})",
                    where,
                )
            )
            if DATASOURCE_NAME.fullmatch(name):
                return name, "not_defined"
            return "", "not_a_name"
        return name, "defined"

    # -- checks --

    def _load_check(
        self, source: YAMLSource, dataset: Dataset, checks: CommentedSeq, index: int
    ) -> Check | None:
        item = checks[index]
        options_node: CommentedMap
        if isinstance(item, str):
            text = str(item)
            text_at = source.of_item(checks, index).shifted(quote_offset(item))
            options_node = CommentedMap()
        elif isinstance(item, CommentedMap) and len(item) == 1:
            key = next(iter(item))
            text = str(key)
            text_at = source.of_key(item, key).shifted(quote_offset(key))
            value = item[key]
            if value is None:
                options_node = CommentedMap()
            elif isinstance(value, CommentedMap):
                options_node = value
            else:
                self.diagnostics.append(
                    error(
                        f"options for '{text}' must be a mapping",
                        source.of_value(item, key),
                    )
                )
                return None
        else:
            self.diagnostics.append(
                error(
                    "a check is an expression, or one `expression: {options}` mapping",
                    source.of_item(checks, index),
                )
            )
            return None

        try:
            expression = parse_check(text)
        except DSLSyntaxError as exc:
            self.diagnostics.append(error(exc.message, text_at.shifted(exc.offset)))
            return None

        metric = get_metric(expression.metric.name)
        if metric is None and expression.change is not None:
            self.diagnostics.append(
                error(
                    "expected a metric such as row_count inside change(...)",
                    text_at.shifted(len("change(")),
                )
            )
            return None
        if metric is None:
            hint = suggest_metric(expression.metric.name)
            did_you_mean = f" — did you mean '{hint}'?" if hint else ""
            self.diagnostics.append(
                error(
                    f"unknown metric '{expression.metric.name}'{did_you_mean}", text_at
                )
            )
            return None

        problems_before = len(self.diagnostics)
        if expression.change is not None:
            problem = _change_problem(metric)
            if problem is not None:
                self.diagnostics.append(error(problem, text_at))
                return None
        self._check_arguments(metric, expression.metric.args, text_at)

        allowed = (
            *COMMON_CHECK_KEYS,
            *(("where",) if metric.scoped else ()),
            *metric.options,
        )
        self._reject_unknown(source, options_node, allowed, f"option for {metric.name}")
        options: dict[str, Any] = {}
        for key, kind in metric.options.items():
            if key not in options_node:
                continue
            if kind is OptionType.VALUE_LIST:
                values = self._value_list(source, options_node, key, metric)
                if values is not None:
                    options[key] = values
            elif self._option_ok(source, options_node, key, kind):
                options[key] = plain(options_node[key])

        warn = self._trigger(source, options_node, "warn")
        fail = self._trigger(source, options_node, "fail")
        expectation = expression.condition
        if expectation is not None and (warn is not None or fail is not None):
            self.diagnostics.append(
                error(
                    "give either a comparison or warn:/fail: triggers, not both",
                    text_at,
                )
            )
        if (
            expectation is None
            and warn is None
            and fail is None
            and "warn" not in options_node
        ):
            if expression.change is not None:
                # A metric's default rule (failed_rows = 0) says nothing about
                # how much it may move.
                if "fail" not in options_node:
                    self.diagnostics.append(
                        error(
                            f"{expression.subject} needs a comparison or triggers, "
                            f"e.g. {expression.subject} > -20%",
                            text_at.shifted(len(text.rstrip())),
                        )
                    )
            elif metric.default_condition is not None:
                expectation = metric.default_condition
            elif "fail" not in options_node:
                self.diagnostics.append(
                    error(
                        f"expected a comparison after '{expression.metric}' — "
                        f"e.g. '{expression.metric} > 0' — or warn:/fail: triggers",
                        text_at.shifted(len(text.rstrip())),
                    )
                )

        for condition, at in (
            (expression.condition, text_at),
            (
                warn,
                source.of_value(options_node, "warn")
                if "warn" in options_node
                else text_at,
            ),
            (
                fail,
                source.of_value(options_node, "fail")
                if "fail" in options_node
                else text_at,
            ),
        ):
            if condition is not None and expression.change is None:
                self._check_units(metric, condition, at)
        if expression.change is not None:
            self._check_change_units(
                expression.subject,
                [c for c in (expression.condition, warn, fail) if c],
                text_at,
            )

        # Semantic rules only once the syntax is clean: a mistyped option is
        # dropped from `options`, and reporting it as missing too would be a
        # second, misleading error for the same mistake.
        if not has_errors(self.diagnostics[problems_before:]):
            for message in metric.validate(options, expression.metric.args):
                self.diagnostics.append(error(message, text_at))

        if len(self.diagnostics) > problems_before and has_errors(
            self.diagnostics[problems_before:]
        ):
            return None

        canonical = canonical_text(expression, warn, fail)
        check_id = self._string(source, options_node, "id")
        if check_id is not None and not ID_PATTERN.match(check_id):
            self.diagnostics.append(
                error(
                    f"invalid id '{check_id}' — use letters, digits, '.', '_', ':' or '-'",
                    source.of_value(options_node, "id"),
                )
            )
            return None
        if check_id is not None and len(check_id) > MAX_ID_LENGTH:
            self.diagnostics.append(
                error(
                    f"id is {len(check_id)} characters — at most {MAX_ID_LENGTH}",
                    source.of_value(options_node, "id"),
                )
            )
            return None
        where = self._string(source, options_node, "where")
        own_notify = self._notify(source, options_node)
        check_id = check_id or derive_check_id(
            dataset.path,
            dataset.name,
            canonical,
            where,
            identity=[
                (name, str(options[name]))
                for name in metric.identity_options
                if name in options
            ],
        )
        if check_id in self._ids:
            self.diagnostics.append(
                error(
                    f"duplicate check (also at {self._ids[check_id]}) — "
                    "give one of them an explicit `id:`",
                    text_at,
                )
            )
            return None
        self._ids[check_id] = text_at

        return Check(
            id=check_id,
            name=self._string(source, options_node, "name") or canonical,
            dataset=dataset,
            metric=metric,
            expression=expression,
            location=text_at,
            expectation=expectation,
            warn=warn,
            fail=fail,
            where=where,
            options=options,
            notify=dataset.notify if own_notify is None else own_notify,
        )

    def _check_arguments(
        self, metric: Metric, args: tuple[str, ...], at: SourceLocation
    ) -> None:
        count = len(args)
        low, high = metric.min_args, metric.max_args
        if low <= count and (high is None or count <= high):
            return
        if high == 0:
            wanted = "no arguments"
        elif high is None:
            wanted = f"at least {low} column{'s' if low > 1 else ''}"
        elif low == high:
            wanted = f"exactly {low} column{'s' if low > 1 else ''}"
        else:
            wanted = f"{low} to {high} arguments"
        self.diagnostics.append(error(f"{metric.name} takes {wanted}, got {count}", at))

    def _check_change_units(
        self, subject: str, conditions: list[Condition], at: SourceLocation
    ) -> None:
        """A change is relative (`%`) or absolute (plain numbers), never both."""
        values = [v for c in conditions for v in values_in(c)]
        if any(isinstance(v, Duration) for v in values):
            self.diagnostics.append(
                error(f"{subject} counts or adds; a duration cannot measure it", at)
            )
            return
        kinds = {isinstance(v, Number) and v.percent for v in values}
        if len(kinds) > 1:
            self.diagnostics.append(
                error(
                    f"{subject}: use % throughout (a relative change) or plain "
                    "numbers throughout (an absolute change), not both",
                    at,
                )
            )

    def _check_units(
        self, metric: Metric, condition: Condition, at: SourceLocation
    ) -> None:
        for value in values_in(condition):
            problem: str | None = None
            if isinstance(value, Duration):
                if metric.unit is not Unit.DURATION:
                    problem = f"'{value}' is a duration, but {metric.name} is not"
            elif metric.unit is Unit.DURATION:
                problem = (
                    f"{metric.name} is a duration — give a unit, e.g. '< {value}h'"
                )
            elif value.percent and metric.unit is not Unit.PERCENT:
                alternative = metric.name.removesuffix("_count") + "_percent"
                hint = (
                    f" — did you mean {alternative}?"
                    if get_metric(alternative) is not None
                    else ""
                )
                problem = f"'{value}' is a percentage, but {metric.name} is not{hint}"
            if problem:
                self.diagnostics.append(error(problem, at))

    def _trigger(
        self, source: YAMLSource, node: CommentedMap, key: str
    ) -> Condition | None:
        if key not in node:
            return None
        value = node[key]
        at = source.of_value(node, key)
        if not isinstance(value, str):
            self.diagnostics.append(
                error(f"`{key}:` takes a trigger such as 'when < 10'", at)
            )
            return None
        try:
            return parse_trigger(str(value))
        except DSLSyntaxError as exc:
            self.diagnostics.append(
                error(exc.message, at.shifted(quote_offset(value) + exc.offset))
            )
            return None

    # -- small typed getters, each reporting its own problems --

    def _reject_unknown(
        self, source: YAMLSource, node: CommentedMap, allowed: Iterable[str], what: str
    ) -> None:
        allowed = list(allowed)
        for key in node:
            if key not in allowed:
                hint = difflib.get_close_matches(str(key), allowed, n=1)
                did_you_mean = f" — did you mean '{hint[0]}'?" if hint else ""
                self.diagnostics.append(
                    error(
                        f"unknown {what} '{key}'{did_you_mean}",
                        source.of_key(node, key),
                    )
                )

    def _string(self, source: YAMLSource, node: CommentedMap, key: str) -> str | None:
        if key not in node:
            return None
        value = node[key]
        if not isinstance(value, str) or not value.strip():
            self.diagnostics.append(
                error(
                    f"`{key}:` must be a non-empty string", source.of_value(node, key)
                )
            )
            return None
        return str(value)

    def _tags(self, source: YAMLSource, node: CommentedMap) -> tuple[str, ...]:
        if "tags" not in node:
            return ()
        value = node["tags"]
        if isinstance(value, str):
            return (str(value),)
        if isinstance(value, list) and all(isinstance(tag, str) for tag in value):
            return tuple(str(tag) for tag in value)
        self.diagnostics.append(
            error(
                "`tags:` must be a string or a list of strings",
                source.of_value(node, "tags"),
            )
        )
        return ()

    def _notify(self, source: YAMLSource, node: CommentedMap) -> tuple[str, ...] | None:
        """`notify:` as notifier names; None when it is not set (or invalid).

        A name or a list of names, each defined in `tablewatch.yml`; `[]`
        turns notifications off below this level. The shorthand stands for
        the mapping form's `to:` list, which routing (I-11) adds.
        """
        if "notify" not in node:
            return None
        value = node["notify"]
        if isinstance(value, str) and value.strip():
            items: list[tuple[str, SourceLocation]] = [
                (str(value), source.of_value(node, "notify"))
            ]
        elif isinstance(value, CommentedSeq) and all(
            isinstance(v, str) and v.strip() for v in value
        ):
            items = [(str(v), source.of_item(value, i)) for i, v in enumerate(value)]
        else:
            self.diagnostics.append(
                error(
                    "`notify:` must be a notifier name or a list of names",
                    source.of_value(node, "notify"),
                )
            )
            return None
        defined = self.project.config.notifiers
        names: list[str] = []
        for name, at in items:
            if name not in defined:
                known = (
                    f"defined in {PROJECT_FILE}: {', '.join(sorted(defined))}"
                    if defined
                    else f"no notifiers are defined in {PROJECT_FILE}"
                )
                shown = name if NOTIFIER_NAME.fullmatch(name) else "…"
                self.diagnostics.append(
                    error(f"unknown notifier '{shown}' ({known})", at)
                )
            elif name not in names:
                names.append(name)
        return tuple(names)

    def _value_list(
        self, source: YAMLSource, node: CommentedMap, key: str, metric: Metric
    ) -> list[Any] | None:
        """The list's values without nulls, or None when the option is invalid.

        A null item is dropped with a warning (it can never match: NULL is
        always missing); a list or mapping item is an error. Every item is
        reported in one pass. Messages name an item by position and kind,
        never by its content.
        """
        if not self._option_ok(source, node, key, OptionType.VALUE_LIST):
            return None
        items = node[key]
        hint = metric.null_hints.get(key)
        warnings: list[Diagnostic] = []
        errors: list[Diagnostic] = []
        kept: list[Any] = []
        for index, item in enumerate(items):
            number = index + 1
            if item is None:
                where, written = source.of_null_item(items, index)
                if written:
                    why = hint.ignored if hint else "null is not a value"
                    text = (
                        f"`{key}:` item {number} is null and is ignored: {why}. "
                        "To match the text 'NULL', quote it"
                    )
                else:
                    text = (
                        f"`{key}:` item {number} is empty and is ignored: a `-` with "
                        "nothing after it is null in YAML. Fill in the value you "
                        "meant, or delete the line"
                    )
                warnings.append(warning(text, where))
            elif not isinstance(value := plain(item), SINGLE_VALUES):
                # The same test as MetricContext.one_of, so what validate
                # accepts never errors the check at run time.
                kind = (
                    "a list"
                    if isinstance(item, list)
                    else "a mapping"
                    if isinstance(item, dict)
                    else "not a single value"
                )
                errors.append(
                    error(
                        f"`{key}:` items must be single values (text, a number, "
                        f"true/false); item {number} is {kind}",
                        source.of_item(items, index),
                    )
                )
            else:
                kept.append(value)
        # An anchored list reused with `*alias` is one list: warn about it once.
        if id(items) in self._warned_lists:
            warnings = []
        self._warned_lists.add(id(items))
        if errors:
            self.diagnostics.extend(warnings + errors)
            return None
        if not kept and hint is not None and hint.all_null is not None:
            self.diagnostics.append(
                error(
                    f"`{key}:` has no values: {hint.all_null}",
                    source.of_value(node, key),
                )
            )
            return None
        self.diagnostics.extend(warnings)
        return kept or None

    def _option_ok(
        self, source: YAMLSource, node: CommentedMap, key: str, kind: OptionType
    ) -> bool:
        value = node[key]
        ok = _matches(value, kind)
        if not ok:
            self.diagnostics.append(
                error(f"`{key}:` must be a {kind}", source.of_value(node, key))
            )
        return ok


def _matches(value: Any, kind: OptionType) -> bool:
    is_number = isinstance(value, int | float) and not isinstance(value, bool)
    match kind:
        case OptionType.STRING:
            return isinstance(value, str) and bool(value.strip())
        case OptionType.NUMBER:
            return is_number
        case OptionType.INTEGER:
            return isinstance(value, int) and not isinstance(value, bool) and value >= 0
        case OptionType.VALUE_LIST:
            return isinstance(value, list) and len(value) > 0
        case OptionType.STRING_LIST:
            return (
                isinstance(value, list)
                and len(value) > 0
                and all(isinstance(v, str) for v in value)
            )
        case OptionType.MAPPING:
            return isinstance(value, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            )


def _change_problem(metric: Metric) -> str | None:
    """Why `change()` cannot wrap `metric`, or None: counts and numbers only."""
    if metric.name == "schema":
        return "change() works on counts and numbers; schema counts problems, not data"
    if metric.unit is Unit.PERCENT:
        return f"change() works on counts and numbers; {metric.name} is a percentage"
    if metric.unit is Unit.DURATION:
        return f"change() works on counts and numbers; {metric.name} is a duration"
    return None


def _composed(text: str) -> MappingNode | None:
    # Runs after a clean round-trip load, so it should not fail; if it does,
    # that is tablewatch's fault, not the file's: no spans, no diagnostic.
    try:
        return compose(text)
    except Exception:
        log.debug("could not compose a check file for its source spans", exc_info=True)
        return None


def _span(lines: Sequence[str], root: MappingNode, index: int) -> SourceSpan | None:
    try:
        return check_span(lines, root, index)
    except Exception:
        log.debug("could not find a check's source span", exc_info=True)
        return None


def _own_key_line(source: YAMLSource, node: CommentedMap, key: str) -> int | None:
    """The 1-based line of a key written in this mapping; None if absent or merged."""
    own = source.of_own_key(node, key)
    return own.line if own is not None else None
