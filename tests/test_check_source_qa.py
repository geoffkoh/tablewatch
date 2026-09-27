"""Spec 006, adversarial: source spans on YAML layouts the acceptance tests do
not use, and `GET /api/v1/checks/{id}/source` on them.

The bar (security B1/B2): a span is exactly the check's own lines, or it is
unavailable. It never serves a line that belongs to another check or key.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.checks.model import Check, SourceSpan
from tablewatch.config import loader as loader_module
from tests.conftest import invoke
from tests.test_server import get, served

PROJECT = """\
name: qa
datasources:
  lake:
    type: duckdb
    path: qa.duckdb
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "qa"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(PROJECT, encoding="utf-8")
    return root


def _write(root: Path, text: str, name: str = "a.yml") -> None:
    (root / "checks" / name).write_bytes(text.encode("utf-8"))


def _checks(root: Path) -> list[Check]:
    loaded = tw.load(root)
    assert loaded.ok, [str(d) for d in loaded.diagnostics]
    return loaded.checks


def _lines(check: Check) -> tuple[int, int] | None:
    span = check.span
    return None if span is None else (span.start_line, span.end_line)


def _exact_or_unavailable(check: Check, expected: tuple[int, int]) -> None:
    assert _lines(check) in (expected, None), (check.canonical, _lines(check))


# --- B1 (b) / Y19: an alias item never borrows another check's line --------------


ALIAS_TO_A_KEY = """\
dataset: t
checks:
  - &k row_count > 0: {where: a > 1}
  - *k
"""


def test_a_block_alias_to_another_checks_key_is_unavailable(project: Path) -> None:
    # `- *k` is the check `row_count > 0` with no `where:`. Its marks are the
    # anchor's, on line 3, which does hold a `-` at the dash column, so the
    # block post-condition passes and the span is line 3: the other check's
    # line, `where: a > 1` included. Spec B1 (b) and Y19 require unavailable.
    _write(project, ALIAS_TO_A_KEY)
    checks = _checks(project)
    scoped = next(c for c in checks if c.where is not None)
    alias = next(c for c in checks if c.where is None)
    assert scoped.id != alias.id
    assert _lines(scoped) == (3, 3)
    assert alias.span is None


def test_a_block_alias_to_another_checks_key_over_the_api(project: Path) -> None:
    _write(
        project,
        "dataset: t\nchecks:\n  - &k row_count > 0:\n      where: a > 1\n  - *k\n",
    )
    alias = next(c for c in _checks(project) if c.where is None)
    with served(project) as client:
        body = get(client, f"/api/v1/checks/{alias.id}/source")
    assert body["text"] is None or "where" not in body["text"]
    assert body["start_line"] in (None, 5)


# --- rule 5: spans never make the loader raise --------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "<<: {filter: x > 1}\ndataset: t\nchecks:\n  - row_count > 0\n",
        "<<: &b {filter: x > 1}\ndataset: t\nchecks:\n  - row_count > 0\n",
    ],
)
def test_a_merged_filter_does_not_crash_the_loader(project: Path, text: str) -> None:
    # Loads with no problems on main. The new `filter_line` asks ruamel for the
    # `filter` key's position, which a merged key does not have: KeyError.
    _write(project, text)
    loaded = tw.load(project)
    assert loaded.ok
    assert [c.dataset.filter for c in loaded.checks] == ["x > 1"]


def test_validate_on_a_merged_filter_exits_0(project: Path) -> None:
    _write(project, "<<: {filter: x > 1}\ndataset: t\nchecks:\n  - row_count > 0\n")
    code, out, err = invoke(project, "validate")
    assert "Traceback" not in err
    assert code == 0, (out, err)


# --- the load pass stays linear ------------------------------------------------------


def _load_seconds(root: Path) -> float:
    started = time.perf_counter()
    tw.load(root)
    return time.perf_counter() - started


def test_spans_do_not_make_loading_quadratic(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 4000 checks in one file: 0.7 s on main, 24 s on this branch.
    # `_inside_checks_only` walks the whole `checks` subtree once per check.
    body = "".join(
        f"  # c{i}\n  - row_count > {i}:\n      name: n{i}\n" for i in range(3000)
    )
    _write(project, "dataset: t\nchecks:\n" + body)
    with_spans = _load_seconds(project)
    monkeypatch.setattr(loader_module, "check_span", lambda *_: None)
    without = _load_seconds(project)
    assert with_spans < 3 * without + 1, (with_spans, without)


# --- P14's premise: a BOM stays in line 1 and is served ------------------------------


def test_a_bom_flow_file_serves_line_one(project: Path) -> None:
    # Spec P14: "a flow-style file that starts `checks: [row_count > 0]` and
    # names its `dataset:` on line 2 serves it". ruamel does not count U+FEFF
    # as a column, so the flow post-condition compares the wrong character and
    # the span is unavailable.
    _write(project, "\ufeffchecks: [row_count > 0]\ndataset: t\n")
    (check,) = _checks(project)
    assert _lines(check) == (1, 1)
    with served(project) as client:
        body = get(client, f"/api/v1/checks/{check.id}/source")
    assert body["text"] == "\ufeffchecks: [row_count > 0]"


# --- awkward layouts: exactly the check's lines, or unavailable ---------------------

LAYOUTS: list[tuple[str, str, dict[str, tuple[int, int]]]] = [
    (
        "comment between the dash and its content",
        (
            "dataset: t\nchecks:\n  -\n    # note\n    row_count > 0\n"
            "  - missing_count(a) = 0\n"
        ),
        {"row_count > 0": (3, 5), "missing_count(a) = 0": (6, 6)},
    ),
    (
        "keep-chomping block scalar then a key",
        (
            "dataset: t\nchecks:\n  - sql_metric > 0:\n      query: |+\n"
            "        SELECT 1\n\n\nowner: o@example.com\n"
        ),
        {"sql_metric > 0": (3, 5)},
    ),
    (
        "folded strip block scalar with a # line, then a key",
        (
            "dataset: t\nchecks:\n  - sql_metric > 0:\n      query: >-\n"
            "        SELECT 1\n        # not a comment\nowner: o@example.com\n"
        ),
        {"sql_metric > 0": (3, 6)},
    ),
    (
        "double-quoted scalar whose continuation starts with #",
        (
            'dataset: t\nchecks:\n  - sql_metric > 0:\n      query: "SELECT 1\n\n'
            '        # FROM x"\n  # lead\n  - row_count > 0\n'
        ),
        {"sql_metric > 0": (3, 6), "row_count > 0": (7, 8)},
    ),
    (
        "single-quoted continuation starting with #, then a key",
        (
            "dataset: t\nchecks:\n  - sql_metric > 0:\n      query: 'SELECT 1\n"
            "        # FROM x'\nowner: '\n  # hi'\n"
        ),
        {"sql_metric > 0": (3, 5)},
    ),
    (
        "zero-indented list with a column-0 comment between items",
        (
            "dataset: t\nchecks:\n- row_count > 0\n# c\n- missing_count(a) = 0\n"
            "owner: o@example.com\n"
        ),
        {"row_count > 0": (3, 3), "missing_count(a) = 0": (4, 5)},
    ),
    (
        "checks first, then keys, comments at and left of the dash",
        "checks:\n  - row_count > 0\n  # at the dash\n# at 0\ndataset: t\n",
        {"row_count > 0": (2, 2)},
    ),
    (
        "indented root mapping, key after the list",
        "  dataset: t\n  checks:\n  - row_count > 0\n  # c\n  owner: o@example.com\n",
        {"row_count > 0": (3, 3)},
    ),
    (
        "explicit ? key for checks",
        "dataset: t\n? checks\n# between\n:\n  # lead\n  - row_count > 0\n",
        {"row_count > 0": (5, 6)},
    ),
    (
        "nested option list with comments, then a deeper trailing comment",
        (
            "dataset: t\nchecks:\n  - invalid_count(c) = 0:\n      valid_values:\n"
            "      - a\n      # x\n      - b\n    # deeper\n  # lead\n  - row_count > 0\n"
        ),
        {"invalid_count(c) = 0": (3, 8), "row_count > 0": (9, 10)},
    ),
    (
        "anchored and tagged sequences",
        "dataset: t\nchecks: !!seq\n  - row_count > 0\n",
        {"row_count > 0": (3, 3)},
    ),
    (
        "CR-only line breaks",
        "dataset: t\rchecks:\r  - row_count > 0\r  # c\r  - missing_count(a) = 0\r",
        {"row_count > 0": (3, 3), "missing_count(a) = 0": (4, 5)},
    ),
    (
        "mixed CR CRLF LF",
        "dataset: t\r\r\nchecks:\n  - row_count > 0\r\n  # c\r  - missing_count(a) = 0",
        {"row_count > 0": (4, 4), "missing_count(a) = 0": (5, 6)},
    ),
    (
        "%YAML 1.1 with NEL in a quoted dataset",
        (
            '%YAML 1.1\n---\ndataset: "a\u0085\u0085b"\nfilter: x > 1\nchecks:\n'
            "  - row_count > 0\n"
        ),
        {"row_count > 0": (6, 6)},
    ),
    (
        "flow list closing on the line after the last item, key after",
        "dataset: t\nchecks: [row_count > 0\n  ]\nfilter: a > 1\n",
        {"row_count > 0": (2, 2)},
    ),
    (
        "multi-line quoted flow item, key after",
        'dataset: t\nchecks: ["row_count\n  > 0"]\nfilter: a > 1\n',
        {"row_count > 0": (2, 3)},
    ),
]

SEPARATORS = ["\u0085", "\u2028", "\u2029"]
for _sep in SEPARATORS:
    name = f"U+{ord(_sep):04X}"
    LAYOUTS += [
        (
            f"{name} right after checks:",
            f"dataset: t\nchecks:{_sep}\n  - row_count > 0\n",
            {"row_count > 0": (3, 3)},
        ),
        (
            f"{name} in a plain dataset value",
            f"dataset: t{_sep}\nchecks:\n  - row_count > 0\n",
            {"row_count > 0": (3, 3)},
        ),
        (
            f"{name} at the end of an item",
            f"dataset: t\nchecks:\n  - row_count > 0{_sep}\n  - missing_count(a) = 0\n",
            {"row_count > 0": (3, 3), "missing_count(a) = 0": (4, 4)},
        ),
        (
            f"{name} in a quoted filter above a flow list",
            f'dataset: t\nfilter: "a{_sep}{_sep}{_sep}"\nchecks: [row_count > 0]\n',
            {"row_count > 0": (3, 3)},
        ),
        (
            f"{name} in a check's name",
            (
                f'dataset: t\nfilter: "x > 1"\nchecks:\n  - row_count > 0:\n'
                f'      name: "a{_sep}b"\n  - missing_count(a) = 0\n'
            ),
            {"row_count > 0": (4, 5), "missing_count(a) = 0": (6, 6)},
        ),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [pytest.param(t, e, id=n) for n, t, e in LAYOUTS],
)
def test_awkward_layouts_are_exact_or_unavailable(
    project: Path, text: str, expected: dict[str, tuple[int, int]]
) -> None:
    _write(project, text)
    checks = _checks(project)
    assert sorted(c.canonical for c in checks) == sorted(expected)
    for check in checks:
        _exact_or_unavailable(check, expected[check.canonical])


@pytest.mark.parametrize(
    ("text", "expected"),
    [pytest.param(t, e, id=n) for n, t, e in LAYOUTS],
)
def test_awkward_layouts_never_serve_another_key(
    project: Path, text: str, expected: dict[str, tuple[int, int]]
) -> None:
    _write(project, text)
    checks = _checks(project)
    with served(project) as client:
        bodies = [get(client, f"/api/v1/checks/{c.id}/source") for c in checks]
    for body in bodies:
        for line in (body["text"] or "").split("\n"):
            stripped = line.lstrip("\ufeff ")
            for key in ("dataset:", "filter:", "owner:", "%YAML", "---"):
                assert not stripped.startswith(key), (body["check_id"], line)


# --- the model: a span is never part of identity -------------------------------------


def test_the_span_does_not_feed_identity(project: Path) -> None:
    _write(project, "dataset: t\nchecks:\n  - row_count > 0\n")
    (plain,) = _checks(project)
    _write(
        project, "dataset: t\n\n\nchecks:\n  # moved and commented\n  - row_count > 0\n"
    )
    (moved,) = _checks(project)
    assert plain.id == moved.id
    assert _lines(moved) == (5, 6)
    assert isinstance(moved.span, SourceSpan)


def test_a_compose_failure_changes_nothing_but_spans(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # rule 5, architect F4
    _write(
        project, "dataset: t\nchecks:\n  - row_count > 0\n  - missing_count(a) = 0\n"
    )
    before = invoke(project, "validate")

    def broken(text: str) -> None:
        raise RuntimeError("compose failed")

    monkeypatch.setattr(loader_module, "compose", broken)
    after = invoke(project, "validate")
    assert after == before
    loaded = tw.load(project)
    assert loaded.ok and not loaded.diagnostics
    assert [c.span for c in loaded.checks] == [None, None]


def test_a_flow_alias_to_another_checks_key_is_unavailable(project: Path) -> None:
    _write(project, "dataset: t\nchecks: [{&k row_count > 0: {where: a > 1}}, *k]\n")
    alias = next(c for c in _checks(project) if c.where is None)
    assert alias.span is None


def test_the_readme_says_who_can_read_check_files() -> None:  # X4, Y16
    readme = " ".join(
        (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8").split()
    )
    assert (
        "Anyone who can reach the server can read your check files, comments included."
        in readme
    )
    assert "never in a check file or a comment" in readme
    assert "A symbolic link is shown under its own name." in readme
