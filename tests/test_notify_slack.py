"""Spec 019: the Slack notifier.

Every POST goes to a local server on 127.0.0.1; no test calls Slack.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.notify.payload import Payload, PayloadCheck, PayloadEvent, PayloadRun
from tablewatch.notify.slack import MAX_HEADER, MAX_SECTION, render_payload
from tests.conftest import EXAMPLES, invoke
from tests.test_notify import (  # noqa: F401 - fixtures
    ORDERS,
    TABLEWATCH_YML,
    Hook,
    _write,
    hook,
    second_hook,
    set_rows,
)

RLO = chr(0x202E)  # right-to-left override

SLACK_YML = TABLEWATCH_YML.replace("data-alerts:", "sales-slack:").replace(
    "type: webhook", "type: slack"
)


@pytest.fixture
def project(tmp_path: Path, hook: Hook) -> Path:  # noqa: F811
    root = tmp_path / "s"
    _write(root, "tablewatch.yml", SLACK_YML)
    _write(root, "checks/sales/_defaults.yml", "notify: sales-slack\n")
    _write(root, "checks/sales/orders.yml", ORDERS)
    set_rows(root, "a", "b", "c")
    return root


# --- building payloads by hand --------------------------------------------------


def event(
    kind: str = "failing",
    *,
    name: str = "has a",
    dataset: str = "orders",
    owner: str | None = None,
    message: str | None = None,
    display_value: str = "0 rows",
) -> PayloadEvent:
    outcome = {"failing": "fail", "erroring": "error", "recovered": "pass"}[kind]
    return PayloadEvent(
        event=kind,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        previous_outcome=None,
        check=PayloadCheck(
            id="0123456789abcdef",
            name=name,
            path="checks/sales/orders.yml",
            dataset=dataset,
            datasource="lake",
            owner=owner,
            tags=[],
        ),
        value=0.0,
        display_value=display_value,
        message="could not evaluate" if kind == "erroring" else message,
    )


def payload(*events: PayloadEvent, project: str = "retail-example") -> Payload:
    return Payload(
        schema_version=1,
        project=project,
        notifier="sales-slack",
        run=PayloadRun(
            id="3f2a91c0aaaa",
            started_at=datetime(2026, 10, 2, 8, tzinfo=UTC),
            trigger="cli",
        ),
        events=list(events),
    )


def sections(body: dict[str, Any]) -> list[str]:
    return [b["text"]["text"] for b in body["blocks"] if b["type"] == "section"]


def header(body: dict[str, Any]) -> str:
    text: str = body["blocks"][0]["text"]["text"]
    return text


# --- layout and wording -------------------------------------------------------------


def test_layout() -> None:  # S2
    body = render_payload(
        payload(
            event("failing", name="has a"),
            event("recovered", name="has r", display_value="3 rows"),
            event("erroring", name="has e"),
            event(
                "failing",
                name="has b",
                owner="sales@example.com",
                message="rule broken",
            ),
        )
    )
    expected = "retail-example: 2 failing, 1 could not evaluate, 1 recovered"
    assert body["text"] == expected
    assert header(body) == expected
    assert body["blocks"][0]["text"] == {
        "type": "plain_text",
        "text": expected,
        "emoji": False,
    }
    assert sections(body) == [
        (
            "*Failing (2)*\n"
            "• orders · has a: 0 rows\n"
            "• orders · has b: 0 rows — rule broken (owner: sales@example.com)"
        ),
        "*Could not evaluate (1)*\n• orders · has e: could not evaluate",
        "*Recovered (1)*\n• orders · has r: 3 rows",
    ]
    assert body["blocks"][-1] == {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "run 3f2a91c0 · cli · 2026-10-02 08:00 UTC",
                "verbatim": True,
            }
        ],
    }
    assert body["unfurl_links"] is False
    assert body["unfurl_media"] is False
    for block in body["blocks"][1:-1]:
        assert block["text"]["verbatim"] is True


def test_only_recoveries() -> None:  # S3
    body = render_payload(payload(event("recovered"), event("recovered", name="x")))
    assert body["text"] == "retail-example: 2 recovered"
    assert [s.split("\n")[0] for s in sections(body)] == ["*Recovered (2)*"]


def test_a_plain_line_has_no_dangling_separator() -> None:  # S23
    body = render_payload(payload(event(name="row_count > 0")))
    assert sections(body)[0].split("\n")[1] == "• orders · row_count &gt; 0: 0 rows"


def test_a_value_sits_beside_its_message() -> None:  # S9
    line = sections(
        render_payload(
            payload(event(display_value="2 days", message="newest 2026-09-30"))
        )
    )[0]
    assert line.endswith("• orders · has a: 2 days — newest 2026-09-30")


# --- escaping ---------------------------------------------------------------------------


def test_mentions_never_ping() -> None:  # S4
    raw = json.dumps(render_payload(payload(event(name="<!channel> & <!here>"))))
    assert "&lt;!channel&gt; &amp; &lt;!here&gt;" in raw
    assert "<!" not in raw


def test_every_user_string_is_escaped() -> None:  # S5, S6
    body = render_payload(
        payload(
            event(
                name="<https://evil.example|click>",
                dataset="<@U123>",
                owner="<!subteam^S1>",
                message="row is <b>",
            ),
            project="<!channel>",
        )
    )
    for block in body["blocks"]:
        if block["type"] != "header":
            assert "<" not in json.dumps(block)
    assert "<" not in body["text"]
    assert "&lt;https://evil.example|click&gt;" in sections(body)[0]


def test_entities_are_escaped_again() -> None:  # S7
    assert "&amp;amp;" in sections(render_payload(payload(event(name="&amp;"))))[0]


def test_bare_mentions_arrive_as_written() -> None:  # S26
    body = render_payload(payload(event(name="@here @channel #general")))
    assert "@here @channel #general" in sections(body)[0]
    assert "link_names" not in body
    assert "parse" not in body


def test_no_string_adds_a_line_or_reverses_text() -> None:  # S27
    body = render_payload(payload(event(name=f"x\n*Recovered (9)*{RLO}evil")))
    lines = sections(body)[0].split("\n")
    assert lines[1] == "• orders · x *Recovered (9)* evil: 0 rows"
    assert RLO not in json.dumps(body, ensure_ascii=False)


# --- size ----------------------------------------------------------------------------------


def test_a_long_name_is_cut_before_escaping() -> None:  # S10
    section = sections(render_payload(payload(event(name="<" * 1000))))[0]
    line = section.split("\n")[1]
    assert line == "• orders · " + "&lt;" * 200 + "…: 0 rows"
    assert len(section) <= MAX_SECTION


def test_many_events_are_cut_with_a_count() -> None:  # S11
    events = [event(name=f"check number {i:03d} " + "x" * 40) for i in range(500)]
    body = render_payload(payload(*events))
    assert body["text"] == "retail-example: 500 failing"
    section = sections(body)[0]
    assert len(section) <= MAX_SECTION
    shown = section.count("\n• ")
    assert section.endswith(f"…and {500 - shown} more failing")
    assert len(body["blocks"]) <= 6


def test_one_left_over_is_singular() -> None:  # S24
    long = "y" * 190
    errors = [event("erroring", name=f"{i}{long}", dataset="d" * 190) for i in range(8)]
    section = sections(render_payload(payload(*errors)))[0]
    shown = section.count("\n• ")
    left = 8 - shown
    assert left >= 1
    assert section.endswith(f"…and {left} more {'error' if left == 1 else 'errors'}")
    # find a count that leaves exactly one over
    for count in range(2, 40):
        section = sections(render_payload(payload(*errors[:1] * count)))[0]
        if count - section.count("\n• ") == 1:
            assert section.endswith("…and 1 more error")
            break
    else:
        pytest.fail("no count left exactly one over")


def test_a_long_project_name_fits_the_header() -> None:  # S28
    body = render_payload(payload(event(), project="p" * 200))
    assert len(header(body)) <= MAX_HEADER
    assert body["text"].endswith(": 1 failing")


def test_same_dataset_name_on_two_datasources_reads_the_same() -> None:  # S25
    a = event(dataset="orders")
    b = event(dataset="orders")
    lines = sections(render_payload(payload(a, b)))[0].split("\n")[1:]
    assert lines[0] == lines[1]


# --- end to end --------------------------------------------------------------------------


def test_a_failure_reaches_slack(project: Path, hook: Hook) -> None:  # noqa: F811  # S1
    tw.run(project)
    set_rows(project, "b", "c")
    assert tw.run(project).exit_code() == 1
    assert len(hook.bodies) == 1
    body = hook.bodies[0]
    assert set(body) == {"text", "blocks", "unfurl_links", "unfurl_media"}
    assert sections(body) == [
        "*Failing (1)*\n• orders · has a: 0 rows — expected &gt; 0"
    ]


def test_an_error_keeps_its_text_out(project: Path, hook: Hook) -> None:  # noqa: F811  # S8
    import sqlite3
    from contextlib import closing

    tw.run(project)
    with closing(sqlite3.connect(project / "data.sqlite")) as con, con:
        con.execute("DROP TABLE orders")
        con.execute("CREATE TABLE orders (other TEXT)")
    tw.run(project)
    raw = json.dumps(hook.bodies)
    assert "could not evaluate" in raw
    assert "no such column" not in raw


@pytest.mark.parametrize("status", [404, 400, 429])
def test_a_refusal_warns(
    project: Path,
    hook: Hook,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:  # S12
    hook.status = status
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        assert tw.run(project).exit_code() == 1
    assert f"notifier 'sales-slack' could not send: HTTP {status}" in caplog.text
    assert hook.url not in caplog.text
    assert len(hook.bodies) == 1  # no retry


def test_a_literal_url_is_a_diagnostic(project: Path) -> None:  # S13
    _write(
        project,
        "tablewatch.yml",
        SLACK_YML.replace("${env:TW_HOOK}", "https://hooks.slack.com/services/T/B/X"),
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert (
        "tablewatch.yml:7:10: error: a notifier url must be an ${env:NAME}" in out + err
    )
    assert "hooks.slack.com" not in out + err


def test_channel_is_not_a_setting(project: Path) -> None:  # S14
    _write(
        project,
        "tablewatch.yml",
        SLACK_YML + '    channel: "#data"\n    username: bot\n',
    )
    code, out, err = invoke(project, "validate")
    assert code == 3
    text = out + err
    assert "unknown setting 'channel'" in text
    assert "unknown setting 'username'" in text


def test_a_mistyped_type(project: Path) -> None:  # S15
    _write(project, "tablewatch.yml", SLACK_YML.replace("type: slack", "type: slak"))
    code, out, err = invoke(project, "validate")
    assert code == 3
    assert "notifier 'type' must be one of: webhook, slack" in out + err


def test_a_failing_slack_does_not_stop_a_webhook(
    project: Path,
    hook: Hook,  # noqa: F811
    second_hook: Hook,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:  # S16
    _write(
        project,
        "tablewatch.yml",
        SLACK_YML + "  data-alerts:\n    type: webhook\n    url: ${env:TW_HOOK_2}\n",
    )
    _write(
        project, "checks/sales/_defaults.yml", "notify: [sales-slack, data-alerts]\n"
    )
    hook.status = 500
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        tw.run(project)
    assert len(second_hook.bodies) == 1
    assert second_hook.bodies[0]["schema_version"] == 1
    assert caplog.text.count("could not send") == 1
    assert "notifier 'sales-slack' could not send: HTTP 500" in caplog.text


def test_an_unset_url(
    project: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # S17
    monkeypatch.delenv("TW_HOOK")
    for command in ("validate", "list", "compile"):
        assert invoke(project, command)[0] == 0
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        tw.run(project)
    assert (
        "notifier 'sales-slack': environment variable TW_HOOK is not set" in caplog.text
    )


def test_the_retail_example(tmp_path: Path, hook: Hook) -> None:  # noqa: F811  # S18
    root = tmp_path / "retail"
    shutil.copytree(
        EXAMPLES / "retail", root, ignore=shutil.ignore_patterns(".tablewatch")
    )
    config = root / "tablewatch.yml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "notifiers:\n  sales-slack:\n    type: slack\n    url: ${env:TW_HOOK}\n",
        encoding="utf-8",
    )
    defaults = root / "checks" / "_defaults.yml"
    before = defaults.read_text(encoding="utf-8") if defaults.exists() else ""
    defaults.write_text(before + "notify: sales-slack\n", encoding="utf-8")
    first = tw.run(root)
    # The example's database may not be built (CI): then checks are errors.
    failed = sum(r.outcome.value == "fail" for r in first.results)
    errored = sum(r.outcome.value == "error" for r in first.results)
    assert failed + errored
    assert len(hook.bodies) == 1
    lines = sum(s.count("\n• ") for s in sections(hook.bodies[0]))
    assert lines == failed + errored
    tw.run(root)
    assert len(hook.bodies) == 1


def test_nothing_secret_in_the_body(project: Path, hook: Hook) -> None:  # noqa: F811  # S19
    set_rows(project, "b", "c")
    tw.run(project)
    raw = json.dumps(hook.bodies)
    for absent in (
        hook.url,
        "127.0.0.1",
        "lite",
        "checks/sales/orders.yml",
        str(project),
    ):
        assert absent not in raw


def test_editor_schema_knows_slack() -> None:  # S20
    import jsonschema

    from tablewatch.config.jsonschema import project_schema

    validator = jsonschema.Draft202012Validator(project_schema())
    good = {"name": "p", "notifiers": {"s": {"type": "slack", "url": "${env:X}"}}}
    assert not list(validator.iter_errors(good))
    bad = {
        "name": "p",
        "notifiers": {"s": {"type": "slack", "url": "${env:X}", "channel": "c"}},
    }
    assert list(validator.iter_errors(bad))


def test_owner_and_domains_are_verbatim() -> None:  # S22
    body = render_payload(
        payload(event(owner="sales-data@example.com", message="see example.com"))
    )
    for block in body["blocks"][1:]:
        texts = [block["text"]] if "text" in block else block["elements"]
        assert all(t["verbatim"] is True for t in texts)
