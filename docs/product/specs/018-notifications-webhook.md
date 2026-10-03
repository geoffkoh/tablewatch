# Spec 018: Notifications 1, part 1: the notifier seam, a webhook, `notify:` and state changes (I-06)

- **Track:** full (new seam, outbound network calls, secrets, a new wire contract, a public API flag).
- **Size:** one iteration: part 1 of I-06 (M). Part 2 (iteration 19): `type: slack`, its message formatting and mrkdwn escaping.
- **Reviewers:** architect (REFINE), security-reviewer (REFINE), data-steward (REFINE + VERIFY), qa-engineer (VERIFY).

## Problem and persona

Sam owns a domain's data quality but does not watch a terminal or the web UI; today a failure reaches
him only if Dana forwards it, or when an analyst notices bad numbers. Dana copes by wrapping
`tablewatch run` in a shell script that greps the output and posts to chat, which pages on every run
of a known failure until people mute it. Priya wants alerts into the tooling she already runs (an
incident router, an internal bot), which takes a generic JSON webhook. Principle 2: alert on the
change, then stay silent. Research: [Elementary](https://docs.elementary-data.com/oss/guides/alerts/alerts-configuration) and [GX](https://docs.greatexpectations.io/docs/reference/api/checkpoint/slacknotificationaction_class/) do not alert on state change by default.

## The language (proposed; REFINE may change it)

```yaml
# tablewatch.yml
notifiers:
  data-alerts:
    type: webhook
    url: ${env:TW_DATA_ALERTS_URL}     # the whole value is one ${env:} reference
```
```yaml
# checks/sales/_defaults.yml           (also allowed at dataset level and on a single check)
notify: data-alerts                    # a name or a list of names; nearest level wins; [] turns it off
```

## Events (the state-change rule)

Computed per check in a recorded run from its project-scoped history by `transition()` in
`results/state.py` (BACKLOG I-06: the same rule as "failing since"). Unknown outcomes count as
`error`; `skipped` is always passed over; see D1 for `warn` and `error`, and N27 for the error streak:

| This result | Event when | Event |
| --- | --- | --- |
| `fail` | the newest `fail` or `pass` before it is not `fail`, or there is none (D1) | `failing` |
| `error` (or unknown) | the newest non-`skipped` result before it is not `error`, or there is none | `erroring` |
| `pass` | the newest `fail` or `pass` before it is `fail` (D1) | `recovered` |
| `warn` | never (D1) | — |
| `skipped` | never | — |

Delivery: after the run is recorded, one `POST` per notifier per run that has at least one event,
`Content-Type: application/json`, a 10-second timeout, no retry. A failure to send is a WARNING line
on stderr naming the notifier and the reason (status code or error class), never the URL. **It never
changes the exit code** and is not a `record_errors` entry (BACKLOG I-06, from iteration 1: a notifier
catches and logs its own failures). The exit-code contract in `cli/main.py` is unchanged.

Payload (`schema_version` 1; times as the API writes them):
```json
{"schema_version": 1, "project": "retail-example", "notifier": "data-alerts",
 "run": {"id": "…", "started_at": "2026-10-02T08:00:00.000000Z", "trigger": "cli"},
 "events": [{"event": "failing", "outcome": "fail", "previous_outcome": "pass",
   "check": {"id": "…", "name": "…", "path": "checks/sales/orders.yml", "dataset": "orders",
             "datasource": "lake", "owner": "sales-data@example.com", "tags": ["sales"]},
   "value": 3.0, "display_value": "3 rows", "message": "…"}]}
```

## Scenarios

Tests use a local HTTP server on 127.0.0.1 started by the test; no test calls a real service.
"Project P" = a `tablewatch.yml` with notifier `data-alerts` (url `${env:TW_HOOK}`, set to the
local server) and `checks/sales/_defaults.yml` holding `notify: data-alerts`.

| Id | Must/should | Given | Expected |
| --- | --- | --- | --- |
| N1 | must | P; a check whose history is `pass`; this run `fail` | One POST; `events[0].event == "failing"`, `previous_outcome == "pass"`; exit 1 |
| N2 | must | P; same check fails again on the next run | No POST; exit 1 (today: n/a, no notifications exist) |
| N3 | must | history `fail`; this run `error` | One POST, `erroring`; exit 2 |
| N4 | must | history `fail, error` (newest last); this run `fail` | No POST (state.py rule: the error neither ends nor extends the streak) |
| N5 | must | history `fail`; this run `pass` | One POST, `recovered`, `previous_outcome == "fail"`; exit 0 |
| N6 | must | history `fail, error`; this run `pass` | One POST, `recovered`, `previous_outcome == "fail"` (Q2 may add more) |
| N7 | must | a check's first ever result is `fail` / `error` / `pass` | `failing` / `erroring` / no POST |
| N8 | must | this run `skipped` after `fail` | No POST; the next `fail` sends nothing either |
| N9 | must | three checks change state in one run, two do not | Exactly one POST holding three events, in the console's order |
| N10 | must | the server answers 500, or does not answer within the timeout | stderr: `WARNING notifier 'data-alerts' could not send: HTTP 500` (or `: timed out`); exit code as without notifiers; the run is recorded |
| N11 | must | `TW_HOOK` unset at run time | stderr: `WARNING notifier 'data-alerts': environment variable TW_HOOK is not set`; exit unchanged; `validate`, `list`, `compile` exit 0 with it unset |
| N12 | must | `url: https://hooks.example.com/abc` (a literal) | `validate` exits 3: `tablewatch.yml:4:10: error: a notifier url must be an ${env:NAME} reference — it is a secret` |
| N13 | must | `notify: data-alrts` in `checks/sales/orders.yml` line 3 | `checks/sales/orders.yml:3:9: error: unknown notifier 'data-alrts' (defined in tablewatch.yml: data-alerts)`; all such errors in one pass |
| N14 | must | `notify: 3`, `notify: [a, 3]`, `notify: ""` | One Diagnostic each at the value: "`notify:` must be a notifier name or a list of names" |
| N15 | must | `_defaults.yml` `notify: data-alerts`; the dataset sets `notify: []` | That dataset's checks notify nobody |
| N16 | must | a check gains or loses `notify:` | Its check id is unchanged (identity tests); its history continues |
| N17 | must | `tablewatch run --no-store` / `tw.run(record=False)` on P with a changed state | No POST; one INFO line: `notifications not sent: the run is not recorded` |
| N18 | must | the store cannot be written | No POST; exit 2 as today |
| N19 | must | `tablewatch run --no-notify` / `tw.run(notify=False)` | Recorded, no POST |
| N20 | must | any event | `display_value` sits beside `message` (BACKLOG I-06, spec 007 Q4); freshness shows its age |
| N21 | must | a POST body | Holds no row values beyond what `message` already holds (see Q5); no URL, no credentials |
| N22 | must | `examples/retail` with a notifier, run twice | First run: one POST with one `failing` event per planted defect; second run: no POST |
| N23 | must | two notifiers on one check; one returns 500 | The other still receives its POST |
| N24 | should | `notify:` on a single check overrides its dataset's | Only that check's notifiers receive it |
| N25 | should | the JSON Schema for editors | Knows `notify:` and `notifiers:` (`config/jsonschema.py`) |
| N26 | must | docs | `docs/check-language.md` gains a "Notifications" section (syntax, events, payload); README one paragraph |
| N27 | must | history (newest last) `error, skipped`; this run `error` | No POST — a `skipped` run does not start a new error incident |
| N28 | must | history (newest last) `fail, warn`; this run `pass` | One POST, `recovered`, `previous_outcome == "fail"` (D1) — a silent `warn` does not block recovery |
| N34 | must | history `pass, warn`, this run `pass`; separately `fail, warn`, this run `fail` | No POST either way (D1: `warn` neither opens nor closes an alert) |
| N29 | must | history `pass`, this run `warn`; separately history `fail`, this run `warn` | No POST either way (Q1: `warn` sends nothing in part 1, win or lose) |
| N30 | must | history (newest last) `pass, error`; this run `pass` | No POST (Q2: returning to the *same* evaluated outcome across an `error` sends nothing in part 1) |
| N31 | should | a check's expression changes (new id); the old id's history ends `fail`; the new id's first run is `fail` | One POST, `failing`, as a first-ever result for the new id (N7) — the old id's alert is not "continued" |
| N32 | must | `tablewatch run --path checks/sales`; a `checks/marketing` check's state changed since its last run but is not evaluated this run | No event for the marketing check — only checks evaluated this run are considered |
| N33 | should | four consecutive runs alternate `fail, pass, fail, pass` | Four POSTs, one per run: `failing`, `recovered`, `failing`, `recovered` — real flaps are not debounced |

## Non-goals

- Slack (`type: slack` is rejected as an unknown type until part 2), Teams, email, PagerDuty.
- Routing by owner, tag or severity; opt-in `on:` events (`every_fail`, `pass`): I-11.
- Retries, a send queue, a delivery log in the store, or suppression windows.
- De-duplicating two runs of one project recorded at the same moment (each may send).
- Notifications from `serve` (it runs no checks) or a UI for notifiers.
- Signing the payload (HMAC) (D6).

## Decisions (REFINE; Q1–Q8 answered by data-steward, security-reviewer, architect)

- **D1 (Q1, Q2, data-steward; tech lead amended).** The alert state is binary. For the `fail` and `pass`
  rows, look back past `skipped`, `error` **and `warn`** to the newest `fail` or `pass`; the event fires
  when it differs (`fail` with none before it: `failing`; `pass` with none: nothing). So `warn` sends
  nothing (N29); `fail, warn, pass` is `recovered` with `previous_outcome` `fail` (N28 amended);
  `pass, warn, pass` and `fail, warn, fail` send nothing (N34). The `error` row keeps the steward's
  skip-transparent rule (N27). No "resolved" event after `erroring` (N30); both are I-11.
- **D2 (Q3).** `notify:` replaces at the nearest level; `[]` turns it off. **D3 (architect, blocking).** The string/list form is shorthand for I-11's `notify: {to: [...]}`, so
  I-11 extends it without breaking configs. A notifier named `owner` in `tablewatch.yml` is a Diagnostic
  (reserved for I-11's owner routing).
- **D4 (Q7).** A `notify/` package: `base.py` (`Notification`, `Event`, a `Notifier` Protocol with
  `send(n) -> None` raising `NotifyError(reason)`, a `type -> factory` registry), `http.py`
  (`post_json`, reused by Slack), `webhook.py`, `payload.py` (pydantic). Config models are a
  `type`-discriminated union, like `Datasource`. `notify_sink` follows `store_sink` in `default_sinks`;
  it returns at once on `record_errors`, runs each notifier in its own `try`, and never raises.
  `transition()` lives in `results/state.py`. `ResultStore.previous_results(project, check_ids,
  before)` is one project-scoped query that excludes this run and later runs, reading only as deep as
  the rule needs. `notify` is stored on `Check` and never feeds `derive_check_id` (N16). `notify/`
  must not import `server/`: move `utc`/`_finite` to a neutral module. Times serialise as `+00:00`.
- **D5 (Q8).** `tw.run(..., notify=True)` (keyword-only) and `run --no-notify`; a recorded run notifies
  by default (otherwise a notebook run uses up the change silently). `Notifier` is not in `__all__`.
  The payload has its own `schema_version: 1`, with `docs/api/notification.schema.json` generated from
  `payload.py` and a drift test.
- **D6 (security R1–R4, Q4).** `https` only, `http` only to `127.0.0.0/8`, `::1` or `localhost`.
  Use an `OpenerDirector` with only the HTTP(S) handlers, `ssl.create_default_context()`, and no
  verify-off option. Redirects are refused (`redirect not followed`). `timeout=10` per socket
  operation (documented), no retry; any 2xx is sent. Read at most 64 KiB of the response and discard
  it unparsed. No HMAC in part 1.
- **D7 (security R5, blocker adopted; tightened in BUILD).** For `error` events `message` is always the
  fixed `could not evaluate`, never `error_message()` text; the reason stays in the run's results. Other
  outcomes send `message` as is. Revisit with I-31 (spec 024 R6).
- **D8 (security R6–R9, Q6).** `url` is exactly one `${env:NAME}` (N12), resolved only in `send`.
  Reasons come from a fixed set: `HTTP <code>`, `timed out`, `connection failed`, `TLS verification
  failed`, `redirect not followed`, `the url is not https`, `the url is not a valid URL`. Never
  `str(exc)` or `exc_info`. No URL or response body at any log level. The payload holds only the
  listed fields, with `path` relative to the project. The API and UI never expose `notifiers:`.
- **D9 (architect, blocking).** CLAUDE.md rule 6 is amended to "resolved only at the moment of use
  (`create_engine_for`, `Notifier.send`), through `resolve_env`". Its intent is unchanged.
