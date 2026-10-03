"""Spec 010: a check file or tablewatch.yml never crashes the loader."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

import tablewatch as tw
from tablewatch.diagnostics import ProjectError
from tests.conftest import invoke

CONFIG = "name: p\ndatasources:\n  wh:\n    type: duckdb\n    path: wh.duckdb\n"
T1 = b"dataset: orders\n# a comment \x0c here\nchecks:\n  - row_count > 0\n"
G1 = b"dataset: orders\nchecks:\n  - duplicate_count(a) = 0:\n      name: !!int xyz\n"
M1 = b"dataset: orders\nchecks:\n  - row_count:\n      <<: &base {warn: when < 5}\n"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "p"
    (root / "checks").mkdir(parents=True)
    (root / "tablewatch.yml").write_text(CONFIG, encoding="utf-8")
    db = duckdb.connect(str(root / "wh.duckdb"))
    db.execute(
        "CREATE TABLE orders (a INT, email VARCHAR, phone VARCHAR, postcode VARCHAR)"
    )
    db.execute("INSERT INTO orders VALUES (1, 'x', 'y', 'z')")
    db.close()
    monkeypatch.chdir(root)
    return root


def _file(root: Path, data: bytes, name: str = "checks/orders.yml") -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _validate(root: Path) -> tuple[int, list[str]]:
    code, _, err = invoke(root, "validate")
    return code, [line for line in err.splitlines() if ": error: " in line]


# --- T: unreadable text ------------------------------------------------------------


@pytest.mark.parametrize(
    ("byte", "message"),
    [
        (
            b"\x0c",
            "hidden control character U+000C (form feed) is not allowed; delete it",
        ),
        (
            b"\x0b",
            "hidden control character U+000B (vertical tab) is not allowed; delete it",
        ),
        (
            b"\x08",
            "hidden control character U+0008 (backspace) is not allowed; delete it",
        ),
        (b"\x1b", "hidden control character U+001B (escape) is not allowed; delete it"),
        (b"\x7f", "hidden control character U+007F (delete) is not allowed; delete it"),
        (b"\x07", "hidden control character U+0007 is not allowed; delete it"),
        (b"\x1c", "hidden control character U+001C is not allowed; delete it"),
        (b"\x1d", "hidden control character U+001D is not allowed; delete it"),
        (b"\x1e", "hidden control character U+001E is not allowed; delete it"),
        (b"\xc2\x92", "hidden control character U+0092 is not allowed; delete it"),
        (
            b"\x00",
            (
                "character U+0000 (null) is not allowed; the file may be UTF-16 — "
                "save it as UTF-8"
            ),
        ),
    ],
)
def test_a_forbidden_character(project: Path, byte: bytes, message: str) -> None:  # T1
    _file(project, T1.replace(b"\x0c", byte))
    code, errors = _validate(project)
    assert code == 3
    assert errors == [f"checks/orders.yml:2:13: error: invalid YAML: {message}"]


def test_windows_line_ends(project: Path) -> None:  # T1b
    _file(project, T1.replace(b"\n", b"\r\n"))
    assert _validate(project) == (
        3,
        [
            (
                "checks/orders.yml:2:13: error: invalid YAML: hidden control character "
                "U+000C (form feed) is not allowed; delete it"
            )
        ],
    )


def test_columns_count_characters(project: Path) -> None:  # T2
    _file(project, "dataset: é orders\n# é \x0c\nchecks:\n  - row_count > 0\n".encode())
    _, errors = _validate(project)
    assert errors[0].startswith("checks/orders.yml:2:5: error:")


def test_inside_a_value(project: Path) -> None:  # T3
    _file(
        project, b'dataset: orders\nchecks:\n  - row_count > 0:\n      name: "a\x0bb"\n'
    )
    _, errors = _validate(project)
    assert errors == [
        (
            "checks/orders.yml:4:15: error: invalid YAML: hidden control character "
            "U+000B (vertical tab) is not allowed; delete it"
        )
    ]
    _file(
        project, b'dataset: orders\nchecks:\n  - row_count > 0:\n      name: "a\\fb"\n'
    )
    assert _validate(project) == (0, [])


def test_u_fffe(project: Path) -> None:  # T4
    _file(project, "dataset: orders\n# a ￾ b\nchecks:\n  - row_count > 0\n".encode())
    assert _validate(project)[1] == [
        (
            "checks/orders.yml:2:5: error: invalid YAML: character U+FFFE is not "
            "allowed; delete it"
        )
    ]


def test_utf16_without_a_bom(project: Path) -> None:  # T4b
    _file(project, "dataset: orders\n".encode("utf-16-le"))
    code, errors = _validate(project)
    assert code == 3
    assert errors == [
        (
            "checks/orders.yml:1:2: error: invalid YAML: character U+0000 (null) is not "
            "allowed; the file may be UTF-16 — save it as UTF-8"
        )
    ]


def test_not_utf8(project: Path) -> None:  # T5
    _file(project, b"dataset: orders\n# caf\xe9\nchecks:\n  - row_count > 0\n")
    assert _validate(project) == (
        3,
        [
            (
                "checks/orders.yml:2:6: error: not UTF-8 text: byte 0xE9 cannot be "
                "decoded; save the file as UTF-8"
            )
        ],
    )
    _file(project, b"dataset: orders\r\n# it\x92s\r\nchecks:\r\n  - row_count > 0\r\n")
    assert _validate(project)[1] == [
        (
            "checks/orders.yml:2:5: error: not UTF-8 text: byte 0x92 cannot be decoded; "
            "save the file as UTF-8"
        )
    ]


def test_a_non_utf8_byte_past_8kb(project: Path) -> None:  # T5 (architect)
    padding = b"# " + b"x" * 60 + b"\n"
    _file(project, b"dataset: orders\n" + padding * 200 + b"# caf\xe9\n")
    _, errors = _validate(project)
    assert errors[0].startswith("checks/orders.yml:202:6: error: not UTF-8 text")


@pytest.mark.parametrize("bom", [b"\xff\xfe", b"\xfe\xff"])
def test_utf16_with_a_bom(project: Path, bom: bytes) -> None:  # T5b
    _file(project, bom + "dataset: orders\n".encode("utf-16-le"))
    assert _validate(project)[1] == [
        (
            "checks/orders.yml:1:1: error: not UTF-8 text: the file is UTF-16; save it "
            "as UTF-8"
        )
    ]


def test_the_other_files(project: Path) -> None:  # T6
    _file(project, b"dataset: orders\nchecks:\n  - row_count > 0\n")
    _file(project, b"owner: a\x0cb\n", "checks/_defaults.yml")
    code, errors = _validate(project)
    assert code == 3
    assert errors[0].startswith(
        "checks/_defaults.yml:1:9: error: invalid YAML: hidden control character "
        "U+000C (form feed)"
    )
    (project / "checks" / "_defaults.yml").unlink()
    (project / "tablewatch.yml").write_bytes(CONFIG.encode() + b"# \x0c\n")
    (project / "tablewatch.yml").write_bytes(b"name: p\n# \x0c\n" + CONFIG.encode()[8:])
    code, _, err = invoke(project, "validate")
    assert code == 3
    assert (
        "tablewatch.yml:2:3: error: invalid YAML: hidden control character U+000C"
        in err
    )
    (project / "tablewatch.yml").write_bytes(b"name: caf\xe9\n" + CONFIG.encode()[8:])
    code, _, err = invoke(project, "validate")
    assert code == 3
    assert "tablewatch.yml:1:10: error: not UTF-8 text: byte 0xE9" in err
    with pytest.raises(ProjectError):
        tw.load(project)


def test_one_pass(project: Path) -> None:  # T7
    _file(project, b"dataset: orders\nchecks:\n  - row_count > 0\n")
    _file(project, T1, "checks/zz_broken.yml")
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "checks/zz_broken.yml:2:13: error:" in err
    assert "1 dataset, 1 check" in out + err
    assert invoke(project, "run")[0] == 3


@pytest.mark.parametrize(
    "data",
    [
        b"\xef\xbb\xbfdataset: orders\nchecks:\n  - row_count > 0\n",
        b"dataset: orders\r\nchecks:\r\n  - row_count > 0\r\n",
        b"dataset: orders\rchecks:\r  - row_count > 0\r",
        b"dataset: orders\n# a\ttab\nchecks:\n  - row_count > 0\n",
    ],
)
def test_no_regression(project: Path, data: bytes) -> None:  # T8
    _file(project, data)
    assert _validate(project) == (0, [])


# --- G: tagged values ruamel cannot construct --------------------------------------


@pytest.mark.parametrize("tag", ["int", "float", "bool"])
def test_a_bad_tagged_value(project: Path, tag: str) -> None:  # G1
    _file(project, G1.replace(b"!!int", f"!!{tag}".encode()))
    assert _validate(project) == (
        3,
        [f"checks/orders.yml:4:13: error: invalid YAML: 'xyz' is not a valid !!{tag}"],
    )


@pytest.mark.parametrize("value", [b"!!int 0x", b"!!omap x", b"!!set x"])
def test_other_bad_tags(project: Path, value: bytes) -> None:  # G2
    _file(project, G1.replace(b"!!int xyz", value))
    code, errors = _validate(project)
    assert code == 3
    assert len(errors) == 1
    assert errors[0].startswith("checks/orders.yml:4:13: error: invalid YAML:")


def test_bad_tags_in_the_other_files(project: Path) -> None:  # G3
    (project / "tablewatch.yml").write_text(
        "name: p\ndatasources:\n"
        "  wh: {type: postgres, host: h, database: d, port: !!int x}\n",
        encoding="utf-8",
    )
    code, _, err = invoke(project, "validate")
    assert code == 3
    assert "tablewatch.yml:3:52: error: invalid YAML: 'x' is not a valid !!int" in err
    (project / "tablewatch.yml").write_text(CONFIG, encoding="utf-8")
    _file(project, b"dataset: orders\nchecks:\n  - row_count > 0\n")
    _file(project, b"owner: !!int x\n", "checks/_defaults.yml")
    _, errors = _validate(project)
    assert errors[0].startswith("checks/_defaults.yml:1:8: error:")


# --- M: merge keys -----------------------------------------------------------------


def test_the_reported_merge_loads_and_runs(project: Path) -> None:  # M1
    _file(project, M1)
    code, out, _ = invoke(project, "validate")
    assert (code, out) == (0, "1 dataset, 1 check — no problems found\n")
    [result] = tw.run(project, record=False).results
    assert (result.outcome.value, result.value) == ("warn", 1.0)
    _file(project, M1.replace(b"warn", b"fail"))
    assert _validate(project) == (0, [])


M1B = b"""\
dataset: orders
checks:
  - missing_percent(email):
      <<: &nulls {warn: when > 1%, fail: when > 5%}
  - missing_percent(phone):
      <<: *nulls
  - missing_percent(postcode):
      <<: *nulls
      fail: when > 20%
"""


def test_shared_triggers(project: Path) -> None:  # M1b, M6
    _file(project, M1B)
    project_ = tw.load(project)
    assert project_.ok, project_.diagnostics
    assert [c.fail.__str__() if c.fail else None for c in project_.checks] == [
        "> 5%",
        "> 5%",
        "> 20%",
    ]
    _file(project, M1B.replace(b"when > 1%", b"when > 1d"))
    code, errors = _validate(project)
    assert code == 3
    assert (
        errors
        == [
            "checks/orders.yml:4:25: error: '1d' is a duration, but missing_percent is not"
        ]
        * 3
    )


def test_a_merge_does_not_change_the_id(project: Path) -> None:  # M7
    _file(project, M1B)
    merged = tw.load(project).checks[0].id
    _file(
        project,
        b"dataset: orders\nchecks:\n  - missing_percent(email):\n"
        b"      warn: when > 1%\n      fail: when > 5%\n",
    )
    assert tw.load(project).checks[0].id == merged


@pytest.mark.parametrize(
    ("check", "line4", "diagnostic"),
    [
        (
            "row_count",
            "{warn: 5}",
            "4:18: error: `warn:` takes a trigger such as 'when < 10'",
        ),
        ("row_count", "{warn: when <<}", "4:24: error: expected a number, found '<'"),
        (
            "row_count > 0",
            "{bogus: 1}",
            "4:12: error: unknown option for row_count 'bogus'",
        ),
        (
            "row_count > 0",
            "{name: 5}",
            "4:18: error: `name:` must be a non-empty string",
        ),
        (
            "row_count > 0",
            '{id: "a b"}',
            "4:16: error: invalid id 'a b' — use letters, digits, '.', '_', ':' or '-'",
        ),
    ],
)
def test_a_mistake_in_merged_content(
    project: Path, check: str, line4: str, diagnostic: str
) -> None:  # M2
    _file(
        project, f"dataset: orders\nchecks:\n  - {check}:\n      <<: {line4}\n".encode()
    )
    code, errors = _validate(project)
    assert code == 3
    assert errors == [f"checks/orders.yml:{diagnostic}"]


def test_merges_at_the_item_and_the_root(project: Path) -> None:  # M3
    _file(project, b"dataset: orders\nchecks:\n  - <<: {row_count > 0: {}}\n")
    assert _validate(project) == (0, [])
    assert [r.outcome.value for r in tw.run(project, record=False).results] == ["pass"]
    _file(project, b"<<: {dataset: orders, checks: [row_count > 0]}\n")
    assert _validate(project) == (0, [])
    for root, diagnostic in (
        (
            b"<<: {tags: 5}",
            "1:12: error: `tags:` must be a string or a list of strings",
        ),
        (b"<<: {checks: 5}", "1:14: error: `checks:` must be a list"),
        (
            b"<<: {datasource: nope}",
            "1:18: error: unknown datasource 'nope' (defined in tablewatch.yml: wh)",
        ),
    ):
        rest = b"\ndataset: orders\n" + (
            b"" if b"checks" in root else b"checks:\n  - row_count > 0\n"
        )
        _file(project, root + rest)
        code, errors = _validate(project)
        assert code == 3
        assert f"checks/orders.yml:{diagnostic}" in errors


def test_merges_in_defaults(project: Path) -> None:  # M4
    _file(project, b"dataset: orders\nchecks:\n  - row_count > 0\n")
    _file(project, b"<<: {owner: 5}\n", "checks/_defaults.yml")
    assert (
        "checks/_defaults.yml:1:13: error: `owner:` must be a non-empty string"
        in (_validate(project)[1])
    )
    _file(project, b"<<: {bogus: 5}\n", "checks/_defaults.yml")
    assert (
        "checks/_defaults.yml:1:6: error: unknown setting in _defaults 'bogus'"
        in (_validate(project)[1])
    )
    _file(project, b"<<: {owner: dana, tags: [a]}\n", "checks/_defaults.yml")
    [check] = tw.load(project).checks
    assert (check.dataset.owner, check.dataset.tags) == ("dana", ("a",))


def test_merges_in_tablewatch_yml(project: Path) -> None:  # M5
    (project / "tablewatch.yml").write_text(
        "<<: {name: 5}\n" + CONFIG[8:], encoding="utf-8"
    )
    code, _, err = invoke(project, "validate")
    assert code == 3
    assert "tablewatch.yml:1:12: error: name: Input should be a valid string" in err
    (project / "tablewatch.yml").write_text(
        "name: p\ndatasources:\n  wh:\n    <<: {type: duckdb, path: 5, bogus: 1}\n",
        encoding="utf-8",
    )
    code, _, err = invoke(project, "validate")
    assert code == 3
    assert "tablewatch.yml:4:30: error: path: Input should be a valid string" in err
    assert "tablewatch.yml:4:40: error: unknown setting 'bogus'" in err


def test_own_keys_win(project: Path) -> None:  # M6
    _file(
        project,
        b"dataset: orders\nchecks:\n  - row_count:\n"
        b"      <<: {warn: when < 5}\n      warn: when < 7\n",
    )
    [check] = tw.load(project).checks
    assert str(check.warn) == "< 7"
    _file(
        project,
        b"dataset: orders\nchecks:\n  - row_count:\n"
        b"      <<: {warn: when < 5}\n      warn: 5\n",
    )
    assert _validate(project)[1] == [
        "checks/orders.yml:5:13: error: `warn:` takes a trigger such as 'when < 10'"
    ]
    _file(
        project,
        b"dataset: orders\nchecks:\n  - row_count:\n"
        b"      <<: [&a {warn: when < 1}, &b {warn: when < 2}]\n",
    )
    [check] = tw.load(project).checks
    assert str(check.warn) == "< 1"  # the first merged mapping wins


def test_a_merged_filter_has_no_line_of_its_own(project: Path) -> None:  # architect
    _file(
        project,
        b"dataset: orders\n<<: {filter: a > 0}\nchecks:\n  - row_count > 0\n",
    )
    project_ = tw.load(project)
    assert project_.ok
    assert project_.datasets[0].filter == "a > 0"
    assert project_.datasets[0].filter_line is None


# --- X: every entry point ----------------------------------------------------------


@pytest.mark.parametrize("data", [T1, G1, M1.replace(b"when < 5", b"5")])
def test_every_entry_point(project: Path, data: bytes) -> None:  # X1
    _file(project, data)
    for command in ("validate", "list", "compile", "run"):
        code, _, err = invoke(project, command)
        assert code == 3, (command, err)
        assert "checks/orders.yml:" in err
        assert "Traceback" not in err
    loaded = tw.load(project)
    assert not loaded.ok
    assert loaded.diagnostics
