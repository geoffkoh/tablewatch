"""Documentation that must not fall behind the code."""

from __future__ import annotations

from pathlib import Path

import pytest

from tablewatch.metrics import all_metrics

DOCS = Path(__file__).parent.parent / "docs"


@pytest.mark.parametrize("metric", [m.name for m in all_metrics()])
def test_every_metric_is_documented(metric: str) -> None:
    assert f"`{metric}`" in (DOCS / "check-language.md").read_text()


@pytest.mark.parametrize(
    "option", sorted({option for m in all_metrics() for option in m.options})
)
def test_every_metric_option_is_documented(option: str) -> None:
    assert f"`{option}`" in (DOCS / "check-language.md").read_text()
