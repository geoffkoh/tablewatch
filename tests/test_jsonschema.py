"""The editor schema accepts what the loader accepts, and rejects the rest."""

from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest
from ruamel.yaml import YAML

from tablewatch.config.jsonschema import check_file_schema, project_schema
from tablewatch.metrics import all_metrics
from tests.conftest import EXAMPLES

VALIDATOR = jsonschema.Draft202012Validator(check_file_schema())


def _yaml(text: str) -> object:
    return YAML(typ="safe").load(text)


def test_schema_is_itself_valid() -> None:
    jsonschema.Draft202012Validator.check_schema(check_file_schema())
    jsonschema.Draft202012Validator.check_schema(project_schema())


@pytest.mark.parametrize(
    "path",
    sorted(
        p
        for p in (EXAMPLES / "retail" / "checks").rglob("*.yml")
        if p.name != "_defaults.yml"
    ),
    ids=lambda p: p.name,
)
def test_example_check_files_are_valid(path: Path) -> None:
    VALIDATOR.validate(_yaml(path.read_text()))


def test_every_metric_has_an_options_definition() -> None:
    assert set(check_file_schema()["$defs"]) == {m.name for m in all_metrics()}


@pytest.mark.parametrize(
    "document",
    [
        "checks:\n  - row_count > 0\n",  # no dataset
        "dataset: t\nchecks:\n  - row_cont > 0\n",  # unknown metric
        "dataset: t\nchecks:\n  - avg(a) > 0:\n      whre: x\n",  # unknown option
        "dataset: t\nchecks:\n  - row_count:\n      warn: < 5\n",  # trigger without when
        "dataset: t\nchecks:\n  - schema:\n      where: a > 0\n",  # schema is not scoped
        "dataset: t\nsurprise: 1\nchecks: []\n",
    ],
)
def test_schema_rejects_mistakes(document: str) -> None:
    assert list(VALIDATOR.iter_errors(_yaml(document)))
