"""QA for spec 019 (Slack notifier): escaping, cutting and limits under attack."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

import tablewatch as tw
from tablewatch.notify.payload import PayloadEvent, PayloadRun
from tablewatch.notify.slack import (
    MAX_HEADER,
    MAX_SECTION,
    _line,
    clean,
    escape,
    render_payload,
)
from tests.test_notify import Hook, hook, set_rows  # noqa: F401 - fixtures
from tests.test_notify_slack import (  # noqa: F401
    event,
    header,
    payload,
    project,
    sections,
)

ROOT = Path(__file__).resolve().parent.parent

# An entity split mid-way leaves `&`, `&l`, `&lt`, `&a`, `&am`, `&amp` with no `;`.
_BROKEN_ENTITY = re.compile(r"&(?!(?:amp|lt|gt);)")


def _mrkdwn_texts(body: dict[str, Any]) -> list[str]:
    texts = [body["text"]]
    for block in body["blocks"]:
        if block["type"] == "section":
            texts.append(block["text"]["text"])
        elif block["type"] == "context":
            texts.extend(e["text"] for e in block["elements"])
    return texts


# --- every path a user string takes ---------------------------------------------------


def test_run_id_and_trigger_are_cleaned_and_escaped() -> None:  # D2
    body = render_payload(
        payload(event()).model_copy(
            update={
                "run": PayloadRun(
                    id="<!here>xyz",
                    started_at=payload().run.started_at,
                    trigger="<!channel>\n*x*",
                )
            }
        )
    )
    context = body["blocks"][-1]["elements"][0]["text"]
    assert "<" not in context
    assert "\n" not in context
    assert context.startswith("run &lt;!here&gt;x · &lt;!channel&gt; *x* · ")


def test_display_value_is_escaped() -> None:  # S5: display_value is a user string
    body = render_payload(payload(event(display_value="<!channel> & co")))
    assert "&lt;!channel&gt; &amp; co" in sections(body)[0]
    assert "<" not in json.dumps(body)


def test_project_is_escaped_in_text_but_literal_in_header() -> None:  # D2
    body = render_payload(payload(event(), project="a <!here> & b"))
    assert body["text"] == "a &lt;!here&gt; &amp; b: 1 failing"
    assert header(body) == "a <!here> & b: 1 failing"  # plain_text: not escaped


def test_no_raw_angle_bracket_anywhere_in_mrkdwn() -> None:  # S5, every field at once
    hostile = "<!channel>&<@U1>"
    body = render_payload(
        payload(
            event(
                name=hostile,
                dataset=hostile,
                owner=hostile,
                message=hostile,
                display_value=hostile,
            ),
            event("erroring", name=hostile, dataset=hostile, owner=hostile),
            event(
                "recovered",
                name=hostile,
                dataset=hostile,
                owner=hostile,
                display_value=hostile,
            ),
            project=hostile,
        )
    )
    for text in _mrkdwn_texts(body):
        assert "<" not in text and ">" not in text
        assert not _BROKEN_ENTITY.search(text)


@pytest.mark.parametrize(
    "char",
    [
        "\u2028",  # LINE SEPARATOR: a mandatory line break in Unicode line breaking
        "\u2029",  # PARAGRAPH SEPARATOR
    ],
)
def test_unicode_line_separators_cannot_add_a_line(char: str) -> None:  # D3 intent
    body = render_payload(payload(event(name=f"x{char}*Recovered (9)*")))
    assert char not in json.dumps(body, ensure_ascii=False)


@pytest.mark.parametrize(
    "char",
    ["\u200e", "\u200f", "\u061c"],  # LRM, RLM, ALM: bidi marks outside D3's ranges
)
def test_other_bidi_marks(char: str) -> None:  # D3 intent: no reordering
    body = render_payload(payload(event(name=f"abc{char}def")))
    assert char not in json.dumps(body, ensure_ascii=False)


def test_every_listed_control_becomes_a_space() -> None:  # D3 as written
    controls = [chr(c) for c in range(0x20)] + [chr(c) for c in range(0x7F, 0xA0)]
    controls += [chr(c) for c in range(0x202A, 0x202F)]
    controls += [chr(c) for c in range(0x2066, 0x206A)]
    assert clean("".join(controls)) == " " * len(controls)


def test_lone_surrogates_and_combining_marks_serialise() -> None:
    odd = "\ud800 \udfff \u0301" + "e\u0301" * 300
    body = render_payload(payload(event(name=odd, owner=odd), project=odd))
    raw = json.dumps(body).encode()  # what `Slack.send` posts
    assert json.loads(raw) == body
    # A cut counts code points, never splits a surrogate pair of a real astral char.
    line = sections(render_payload(payload(event(name="😀" * 500))))[0].split("\n")[1]
    assert line == "• orders · " + "😀" * 200 + "…: 0 rows"


def test_long_multibyte_strings_are_cut_by_code_point() -> None:  # S10
    name = "日本&" * 400
    line = sections(render_payload(payload(event(name=name))))[0].split("\n")[1]
    raw = name[:200]
    assert line == f"• orders · {escape(raw)}…: 0 rows"


@pytest.mark.parametrize("ch,entity", [("&", "&amp;"), ("<", "&lt;"), (">", "&gt;")])
def test_a_cut_never_splits_an_entity(ch: str, entity: str) -> None:  # S10
    for length in (199, 200, 201, 299, 300, 301):
        body = render_payload(payload(event(name=ch * length, message=ch * length)))
        for text in _mrkdwn_texts(body):
            assert not _BROKEN_ENTITY.search(text)
        line = sections(body)[0].split("\n")[1]
        assert entity * min(length, 200) in line


# --- truncation arithmetic ----------------------------------------------------------


def _check_section(
    section: str, events: list[PayloadEvent], noun: tuple[str, str]
) -> None:
    lines = section.split("\n")
    assert len(section) <= MAX_SECTION
    body = lines[1:]
    if body and body[-1].startswith("…and "):
        closing, body = body[-1], body[:-1]
        left = len(events) - len(body)
        assert left >= 1
        assert closing == f"…and {left} more {noun[0] if left == 1 else noun[1]}"
    else:
        assert len(body) == len(events)
    # Shown lines are whole, in order: never cut mid-line or mid-entity.
    assert body == [_line(e) for e in events[: len(body)]]


@pytest.mark.parametrize("width", [1, 7, 40, 97, 150, 199, 200, 201])
@pytest.mark.parametrize("count", [1, 2, 9, 10, 11, 99, 100, 101, 1000])
def test_section_cap_and_count_at_digit_boundaries(width: int, count: int) -> None:
    events = [event("erroring", name=f"{i}" + "&" * width) for i in range(count)]
    section = sections(render_payload(payload(*events)))[0]
    _check_section(section, events, ("error", "errors"))


def test_brute_force_the_last_slot() -> None:
    # Sweep the name width so the cap lands at every offset of the closing line.
    for width in range(1, 200, 3):
        events = [event(name="n" * width) for _ in range(120)]
        _check_section(
            sections(render_payload(payload(*events)))[0],
            events,
            ("failing", "failing"),
        )


def test_a_single_line_longer_than_the_cap() -> None:
    worst = "&" * 1000
    e = event(
        name=worst, dataset=worst, owner=worst, message=worst, display_value=worst
    )
    assert len(_line(e)) > MAX_SECTION  # one check can outgrow a section alone
    section = sections(render_payload(payload(e)))[0]
    assert len(section) <= MAX_SECTION
    _check_section(section, [e], ("failing", "failing"))


def test_every_group_truncated_at_once() -> None:  # S11 across all three groups
    long = "<" * 200
    failing = [event("failing", name=f"f{i}{long}") for i in range(300)]
    erroring = [event("erroring", name=f"e{i}{long}") for i in range(300)]
    recovered = [event("recovered", name=f"r{i}{long}") for i in range(300)]
    body = render_payload(payload(*failing, *erroring, *recovered))
    assert len(body["blocks"]) == 5 <= 6
    expected = "retail-example: 300 failing, 300 could not evaluate, 300 recovered"
    assert body["text"] == expected
    assert header(body) == expected
    found = sections(body)
    _check_section(found[0], failing, ("failing", "failing"))
    _check_section(found[1], erroring, ("error", "errors"))
    _check_section(found[2], recovered, ("recovered", "recovered"))
    assert all(s.split("\n")[-1].startswith("…and ") for s in found)


# --- header -------------------------------------------------------------------------


@pytest.mark.parametrize("project_name", ["p" * 200, "日" * 200, "<" * 400])
def test_header_is_at_most_150_code_points(project_name: str) -> None:  # S28, D6
    body = render_payload(payload(event(), project=project_name))
    assert len(header(body)) <= MAX_HEADER
    assert body["text"].endswith(": 1 failing")


def test_header_in_utf16_units() -> None:  # S28
    body = render_payload(payload(event(), project="😀" * 200))
    assert len(header(body).encode("utf-16-le")) // 2 <= MAX_HEADER


def test_a_long_project_keeps_the_totals_in_the_header() -> None:  # docs: "always"
    # docs/check-language.md: "The header always gives the true totals."
    body = render_payload(payload(event(), project="p" * 200))
    assert header(body).endswith(": 1 failing")


def test_header_cleans_controls() -> None:
    body = render_payload(payload(event(), project="a\nb\u202ec"))
    assert header(body) == "a b c: 1 failing"


# --- end to end ---------------------------------------------------------------------


def test_a_timeout_warns(
    project: Path,  # noqa: F811
    hook: Hook,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # S12: timed out
    import tablewatch.notify.http as http

    monkeypatch.setattr(http, "TIMEOUT_SECONDS", 0.2)
    hook.delay = 1.0
    set_rows(project, "b", "c")
    with caplog.at_level(logging.WARNING, logger="tablewatch"):
        assert tw.run(project).exit_code() == 1
    assert "notifier 'sales-slack' could not send: timed out" in caplog.text
    assert hook.url not in caplog.text


def test_the_body_is_valid_json_with_hostile_names(
    project: Path,  # noqa: F811
    hook: Hook,  # noqa: F811
) -> None:  # S4/S5 end to end: through YAML, the runner and the wire
    checks = project / "checks/sales/orders.yml"
    text = checks.read_text(encoding="utf-8")
    checks.write_text(
        text.replace("has a", "<!channel> & has a\u2066"), encoding="utf-8"
    )
    tw.run(project)
    set_rows(project, "b", "c")
    tw.run(project)
    assert len(hook.bodies) == 1
    raw = json.dumps(hook.bodies[0], ensure_ascii=False)
    assert "<" not in raw.replace(header(hook.bodies[0]), "")
    assert "&lt;!channel&gt; &amp; has a " in sections(hook.bodies[0])[0]


def test_docs_describe_slack() -> None:  # S21
    docs = (ROOT / "docs/check-language.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "type: slack" in docs
    for phrase in ("escaped", "200 characters", "…and", "Could not"):
        assert phrase in docs
    assert "type: slack" in readme
