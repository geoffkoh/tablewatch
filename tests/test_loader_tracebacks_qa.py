"""Spec 010, adversarial: nothing a YAML file holds makes the loader raise."""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest

import tablewatch as tw
from tablewatch.diagnostics import ProjectError
from tests.conftest import EXAMPLES, Workspace, invoke

CONFIG = b"name: p\ndatasources:\n  wh:\n    type: duckdb\n    path: wh.duckdb\n"
GOOD = b"dataset: orders\nchecks:\n  - row_count > 0\n"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "p"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_bytes(CONFIG)
    monkeypatch.chdir(root)
    return root


def _write(root: Path, data: bytes, name: str = "checks/orders.yml") -> None:
    (root / name).write_bytes(data)


def _errors(root: Path) -> list[str]:
    return [str(d) for d in tw.load(root).diagnostics if ": error: " in str(d)]


# --- cyclic node graphs on the error path ------------------------------------------
#
# `_bad_tag` walks the composed node graph with no visited set. An alias to
# an enclosing anchor makes that graph cyclic, so any construct failure in
# the same file recurses until RecursionError, which escapes `load` (it is
# raised inside the `except` block). `a: &a {<<: *a}` fails to construct on
# its own (ruamel: AttributeError) and so needs no bad tag at all.

CYCLIC = [
    pytest.param(b"x: &a [*a]\nowner: !!int xyz\n", id="recursive-seq+bad-tag"),
    pytest.param(b"x: &a {k: *a}\nowner: !!int xyz\n", id="recursive-map+bad-tag"),
    pytest.param(b"x: &a {<<: *a}\n", id="recursive-merge"),
    pytest.param(b"x: &a {b: {<<: *a}}\n", id="nested-recursive-merge"),
]


@pytest.mark.parametrize("data", CYCLIC)
def test_a_cyclic_file_is_a_diagnostic_in_a_check_file(
    project: Path, data: bytes
) -> None:
    _write(project, data)
    loaded = tw.load(project)  # must not raise RecursionError
    assert not loaded.ok
    assert any(str(d).startswith("checks/orders.yml:") for d in loaded.diagnostics)


@pytest.mark.parametrize("data", CYCLIC)
def test_a_cyclic_file_is_a_diagnostic_in_defaults(project: Path, data: bytes) -> None:
    _write(project, GOOD)
    _write(project, data, "checks/_defaults.yml")
    loaded = tw.load(project)
    assert any(str(d).startswith("checks/_defaults.yml:") for d in loaded.diagnostics)


@pytest.mark.parametrize("data", CYCLIC)
def test_a_cyclic_tablewatch_yml_is_a_project_error(project: Path, data: bytes) -> None:
    _write(project, GOOD)
    _write(project, CONFIG + data.replace(b"owner", b"other"), "tablewatch.yml")
    with pytest.raises(ProjectError):
        tw.load(project)


@pytest.mark.parametrize("data", CYCLIC)
def test_a_cyclic_file_exits_3_not_a_traceback(project: Path, data: bytes) -> None:
    _write(project, data)
    code, _, err = invoke(project, "validate")
    assert code == 3, err
    assert "Traceback" not in err


# --- where a bad tag is placed -----------------------------------------------------


def test_a_bad_tag_inside_a_tagged_collection_is_placed_at_itself(
    project: Path,
) -> None:
    # Pre-order walk: the parent `!!seq` is rebuilt first, fails because its
    # child fails, and is blamed instead of the `!!int` that is wrong.
    _write(project, b"dataset: orders\ntags: !!seq\n  - a\n  - !!int xyz\nchecks: []\n")
    assert _errors(project) == [
        "checks/orders.yml:4:5: error: invalid YAML: 'xyz' is not a valid !!int"
    ]


def test_a_valid_tagged_value_holding_an_alias_is_not_blamed(project: Path) -> None:
    # The slice `!!seq [*a]` loaded on its own has no anchor `a`, so a valid
    # value is reported and the real mistake on line 4 is not.
    _write(
        project,
        b"dataset: orders\nx: &a t\ntags: !!seq [*a]\nowner: !!int xyz\nchecks: []\n",
    )
    assert _errors(project) == [
        "checks/orders.yml:4:8: error: invalid YAML: 'xyz' is not a valid !!int"
    ]


def test_a_bad_tag_after_a_bom_is_placed_on_its_column(project: Path) -> None:
    _write(project, b"\xef\xbb\xbfdataset: !!int xyz\nchecks: []\n")
    assert _errors(project) == [
        "checks/orders.yml:1:10: error: invalid YAML: 'xyz' is not a valid !!int"
    ]


# --- every forbidden code point ----------------------------------------------------

_FORBIDDEN = [
    *(c for c in range(0x00, 0x20) if c not in (0x09, 0x0A, 0x0D)),
    *(c for c in range(0x7F, 0xA0) if c != 0x85),
    0xFFFE,
    0xFFFF,
]


@pytest.mark.parametrize("code", _FORBIDDEN, ids=lambda c: f"U+{c:04X}")
def test_every_forbidden_code_point(project: Path, code: int) -> None:
    _write(project, f"dataset: orders\n# ab {chr(code)}\nchecks: []\n".encode())
    errors = _errors(project)
    assert len(errors) == 1
    assert errors[0].startswith("checks/orders.yml:2:6: error: invalid YAML: ")
    assert f"U+{code:04X}" in errors[0]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_a_forbidden_character_on_line_1_with_a_bom(
    project: Path, bom: bytes, ending: bytes
) -> None:
    # ReaderError.position counts the BOM; the column must not.
    _write(project, bom + b"dataset: o\x0crders" + ending + b"checks: []" + ending)
    assert _errors(project)[0].startswith("checks/orders.yml:1:11: error: invalid YAML")


@pytest.mark.parametrize("ending", [b"\n", b"\r\n", b"\r"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_a_bad_byte_with_a_bom_and_any_line_end(
    project: Path, bom: bytes, ending: bytes
) -> None:
    _write(project, bom + b"dataset: caf\xe9" + ending + b"# \xe9" + ending)
    assert _errors(project) == [
        (
            "checks/orders.yml:1:13: error: not UTF-8 text: byte 0xE9 cannot be "
            "decoded; save the file as UTF-8"
        )
    ]


def test_a_surrogate_encoded_as_utf8_is_not_utf8(project: Path) -> None:
    _write(project, b"dataset: orders\n# \xed\xa0\x80\n")
    assert _errors(project) == [
        (
            "checks/orders.yml:2:3: error: not UTF-8 text: byte 0xED cannot be "
            "decoded; save the file as UTF-8"
        )
    ]


def test_a_forbidden_character_far_past_8kb(project: Path) -> None:
    padding = (b"# " + b"x" * 100 + b"\r\n") * 500
    _write(project, b"dataset: orders\r\n" + padding + b"# \x1b\r\n")
    assert _errors(project)[0].startswith("checks/orders.yml:502:3: error:")


def test_deep_nesting_is_a_diagnostic(project: Path) -> None:
    _write(project, b"dataset: orders\ntags: " + b"[" * 5000 + b"]" * 5000 + b"\n")
    assert not tw.load(project).ok


# --- merges: nested, lists, aliases of merges --------------------------------------


@pytest.mark.parametrize(
    ("options", "where"),
    [
        (b"<<: {<<: {warn: 5}}", "4:23"),  # a merge of a merge
        (b"<<: [{name: a}, {warn: 5}]", "4:30"),  # the second of a list
        (b"<<: [{<<: {name: a}}, {<<: {warn: 5}}]", "4:41"),  # merges in a list
    ],
)
def test_a_mistake_in_nested_merges_is_placed_where_written(
    project: Path, options: bytes, where: str
) -> None:
    _write(
        project, b"dataset: orders\nchecks:\n  - row_count:\n      " + options + b"\n"
    )
    assert _errors(project) == [
        f"checks/orders.yml:{where}: error: `warn:` takes a trigger such as 'when < 10'"
    ]


def test_an_alias_of_a_merge(project: Path) -> None:
    _write(
        project,
        b"dataset: orders\nchecks:\n  - row_count > 0: &m {<<: {name: 5}}\n"
        b"  - row_count > 1:\n      <<: *m\n",
    )
    assert (
        _errors(project)
        == ["checks/orders.yml:3:35: error: `name:` must be a non-empty string"] * 2
    )


def test_a_merge_inside_a_flow_list_of_checks(project: Path) -> None:
    _write(project, b"dataset: orders\nchecks: [{<<: {row_count > 0: {warn: 5}}}]\n")
    assert _errors(project) == [
        "checks/orders.yml:2:38: error: `warn:` takes a trigger such as 'when < 10'"
    ]


def test_merges_in_the_root_nest(project: Path) -> None:
    _write(project, b"<<: {<<: {checks: 5}}\ndataset: orders\n")
    assert _errors(project) == [
        "checks/orders.yml:1:19: error: `checks:` must be a list"
    ]


def test_a_nested_merge_in_defaults(project: Path) -> None:
    _write(project, GOOD)
    _write(project, b"<<: [{tags: [a]}, {<<: {owner: 5}}]\n", "checks/_defaults.yml")
    assert _errors(project) == [
        "checks/_defaults.yml:1:32: error: `owner:` must be a non-empty string"
    ]


def test_a_nested_merge_in_tablewatch_yml(project: Path) -> None:
    _write(project, GOOD)
    _write(
        project,
        b"name: p\ndatasources:\n  wh:\n    <<: [{type: duckdb}, {<<: {path: 5}}]\n",
        "tablewatch.yml",
    )
    with pytest.raises(ProjectError) as caught:
        tw.load(project)
    assert "tablewatch.yml:4:38: error: path: Input should be a valid string" in str(
        caught.value
    )


def test_a_nested_merged_filter_has_no_line_but_an_own_one_does(project: Path) -> None:
    _write(
        project,
        b"dataset: orders\n<<: {<<: {filter: a > 0}}\nchecks: [row_count > 0]\n",
    )
    [dataset] = tw.load(project).datasets
    assert (dataset.filter, dataset.filter_line) == ("a > 0", None)
    _write(
        project,
        b"dataset: orders\n<<: {filter: a > 0}\nfilter: a > 1\nchecks: [row_count > 0]\n",
    )
    [dataset] = tw.load(project).datasets
    assert (dataset.filter, dataset.filter_line) == ("a > 1", 3)


def test_merged_triggers_keep_the_id_through_a_merge_of_a_merge(project: Path) -> None:
    _write(project, b"dataset: orders\nchecks:\n  - row_count:\n      warn: when < 5\n")
    direct = tw.load(project).checks[0].id
    _write(
        project,
        b"dataset: orders\nchecks:\n  - row_count:\n      <<: {<<: {warn: when < 5}}\n",
    )
    assert tw.load(project).checks[0].id == direct


# --- M1 and M3 on both backends (spec: a run touches a backend) --------------------


@pytest.mark.parametrize("backend", ["duck", "lite"])
def test_merged_options_run_on_both_backends(
    workspace: Workspace, backend: str
) -> None:
    [warned, passed] = workspace.run(
        backend,
        """\
          - row_count:
              <<: &base {warn: when < 10}
          - <<: {row_count > 0: {}}
        """,
    )
    assert (warned.outcome.value, warned.value) == ("warn", 5.0)
    assert passed.outcome.value == "pass"


@pytest.mark.parametrize("backend", ["duck", "lite"])
def test_a_root_merge_runs_on_both_backends(workspace: Workspace, backend: str) -> None:
    workspace.write(
        "checks/t.yml",
        f"<<: {{dataset: t, datasource: {backend}, checks: [row_count > 0]}}\n",
    )
    [result] = tw.run(workspace.root, record=False).results
    assert result.outcome.value == "pass"


# --- X2: random bytes into the retail example --------------------------------------

_TOKENS = [
    b"<<: ",
    b"&a ",
    b"*a",
    b"!!int ",
    b"!!omap ",
    b"!!set ",
    b"{<<: *a}",
    b"&a [*a]",
    b"\xef\xbb\xbf",
    b"\r",
    b"\x00",
    b"\xff",
    b"\xc2",
    b"\x0c",
    b"\n  - ",
    b": ",
    b"{",
    b"[",
    b"'",
    b'"',
    b"? ",
    b"---\n",
]


def _mutations(seed: int, count: int) -> list[tuple[Path, bytes]]:
    rng = random.Random(seed)
    retail = EXAMPLES / "retail"
    files = sorted(p.relative_to(retail) for p in retail.rglob("*.yml"))
    out = []
    for _ in range(count):
        name = rng.choice(files)
        data = bytearray((retail / name).read_bytes())
        for _ in range(rng.randint(1, 3)):
            offset = rng.randint(0, len(data))
            if rng.random() < 0.6:
                data[offset:offset] = rng.choice(_TOKENS)
            else:
                data[offset:offset] = bytes(
                    rng.randrange(256) for _ in range(rng.randint(1, 4))
                )
        out.append((name, bytes(data)))
    return out


@pytest.fixture
def retail_copy(tmp_path: Path) -> Path:
    target = tmp_path / "retail"
    shutil.copytree(
        EXAMPLES / "retail",
        target,
        ignore=shutil.ignore_patterns("*.duckdb", "*.wal", ".tablewatch"),
    )
    return target


def test_random_bytes_never_crash_load(retail_copy: Path) -> None:  # X2
    for name, data in _mutations(seed=10, count=400):
        original = (retail_copy / name).read_bytes()
        (retail_copy / name).write_bytes(data)
        try:
            tw.load(retail_copy)
        except ProjectError:
            assert name.name == "tablewatch.yml", (name, data)
        finally:
            (retail_copy / name).write_bytes(original)


def test_random_bytes_never_make_validate_exit_1(retail_copy: Path) -> None:  # X2
    for name, data in _mutations(seed=11, count=40):
        original = (retail_copy / name).read_bytes()
        (retail_copy / name).write_bytes(data)
        try:
            code, _, err = invoke(retail_copy, "validate")
            assert code in (0, 3), (name, data, err)
        finally:
            (retail_copy / name).write_bytes(original)


def test_a_recursive_alias_and_a_bad_tag_in_retail(retail_copy: Path) -> None:  # X2
    # The one combination the random walk rarely finds.
    path = retail_copy / "checks" / "_defaults.yml"
    path.write_bytes(b"x: &a [*a]\n" + path.read_bytes() + b"y: !!int q\n")
    assert not tw.load(retail_copy).ok
