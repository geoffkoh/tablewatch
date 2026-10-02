# Spec 019: Notifications 1, part 2: `type: slack` (I-06)

- **Track:** full (outbound calls to an external service carrying check data; a new notifier type and message format; a secret URL).
- **Size:** one iteration: part 2 of I-06 (M overall; this part S–M). Completes I-06.
- **Reviewers:** security-reviewer (REFINE), data-steward (REFINE + VERIFY), qa-engineer (VERIFY), architect (VERIFY: no new seam, it reuses spec 018's).

## Problem and persona

Sam lives in Slack, not in a terminal or the web UI. Since iteration 18 a state change can reach him
only if Priya stands up a relay that turns the webhook JSON into a Slack message; Dana copes by
pointing a Slack incoming webhook at the generic payload, which Slack rejects (`no_text`). Sam needs a
readable message, grouped by what changed, in the channel his team already watches. Check names,
datasets, owners and messages are written by many people, so none of them may ping a channel or
become a link. Research: [Slack mrkdwn escaping](https://docs.slack.dev/messaging/formatting-message-text),
[incoming webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks),
[section limits](https://docs.slack.dev/reference/block-kit/blocks/section-block) (3,000 chars; 50 blocks
per message), [Elementary Slack alerts](https://docs.elementary-data.com/oss/guides/alerts/send-slack-alerts).

## The language

```yaml
# tablewatch.yml — same rules as type: webhook (spec 018 D6, D8): url is exactly one ${env:NAME}
notifiers:
  sales-slack:
    type: slack
    url: ${env:TW_SALES_SLACK_URL}
```
No `channel:`, `username:` or `icon:` (incoming webhooks cannot override them). `notify:`, events,
delivery, `--no-notify`, `record=False` and failure handling are exactly spec 018's (D1–D9).

## The seam (fixed by spec 018 D4; no new seam)

`SlackNotifier` config joins the `type`-discriminated `NotifierConfig` union in `config/project.py`
and shares the env-only `url` validator; `NOTIFIER_TYPES` becomes `("webhook", "slack")`.
`notify/slack.py` registers `slack`, renders from the same `Notification` (via `build_payload`, so
D7's fixed error message and D8's field list hold), and sends with `notify/http.py:post_json`. No
`slack_sdk` or other dependency.

## The message (data-steward settled wording and size in REFINE, Q1 and Q4)

One POST per notifier per run. Body: `text` (the notification fallback), `blocks`,
`"unfurl_links": false`, `"unfurl_media": false`.

```
text:    retail-example: 2 failing, 1 could not evaluate, 1 recovered
blocks:  header (plain_text, emoji false)  retail-example: 2 failing, 1 could not evaluate, 1 recovered
         section (mrkdwn, verbatim true)   *Failing (2)*
                                           • orders · row_count > 0: 0 rows (owner: sales-data@example.com)
                                           • ...
         section                           *Could not evaluate (1)*
                                           • customers · freshness(updated_at) < 1d: could not evaluate
         section                           *Recovered (1)*
                                           • ...
         context                           run 3f2a91c0 · cli · 2026-10-02 08:00 UTC
```
- Groups in the fixed order **Failing**, **Could not evaluate** (the `erroring` event), **Recovered** —
  the exact words the console and web UI already use for these states (`status.ts`,
  `LatestResult.tsx`), not the event name. An empty group is left out, and a count of 0 is left out of
  the header and `text` with it; within a group, the console's order (spec 018 N9).
- Per line: `<dataset> · <check name>: <display_value>`, then, only if `message` is not null,
  ` — <message>`, then, only if `owner` is set, ` (owner: <owner>)`. Many checks (a plain comparison
  with nothing more to say) carry no `message`; the line ends at the value, never with a dangling
  separator. `display_value` sits beside `message`, never instead of it (BACKLOG I-06, spec 007 Q4).
  An `error` event shows only the fixed `could not evaluate` in place of both — never the value's `—`
  placeholder (the same rule the frontend already applies, `LatestResult.tsx`) — and the error text
  appears nowhere in the body (D7).
- No `datasource` and no `path`, on a line or anywhere else in the message: the console already names
  a check by dataset and check name alone (it has no `datasource` column either), and Sam cannot open
  a YAML file from Slack on his phone (no links to `serve`; see Non-goals). Anyone who needs the file
  still has the webhook payload and `tablewatch history`.
- **Escaping.** Every user-controlled string (project, check name, dataset, owner, message,
  display_value) has `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;` (in that order) in **every**
  mrkdwn field, including the top-level `text`. Our own labels are the only mrkdwn formatting.
  `plain_text` fields are not escaped (Slack renders them literally).
- **Size.** Each user string is cut to 200 characters (message: 300) with `…`, cut on the raw string
  before escaping so no entity is split. Each section's text stays ≤ 3,000 characters after escaping —
  a character cap, not a cap on lines: a line cap either overshoots Slack's hard limit once names run
  long, or truncates needlessly when many names are short, hiding real failures for no reason. Lines
  are added until the next would pass the cap, then one closing line ends the section: `…and N more
  failing`, `…and N more error`/`errors` (singular at N = 1, as the web UI's own tile already does,
  `Summary.tsx`), `…and N more recovered`. The header and `text` always carry the true totals, even
  when a section is cut. At most 6 blocks, so the 50-block limit cannot be met.
- **Links.** None. tablewatch has no base URL for `serve`, so nothing links to it; non-goal below.

## Scenarios

Tests post to a local HTTP server on 127.0.0.1 (as spec 018); no test calls Slack. "Project S" =
spec 018's project P with `type: slack`, url `${env:TW_SLACK}` set to the local server.

| Id | Must/should | Given | Expected |
| --- | --- | --- | --- |
| S1 | must | S; one check `pass` → `fail` | One POST; JSON with `text`, `blocks`, `unfurl_links: false`, `unfurl_media: false`; a `*Failing (1)*` section; exit 1 |
| S2 | must | S; this run: 2 failing, 1 erroring, 1 recovered, 3 unchanged | One POST; header and `text` read `<project>: 2 failing, 1 could not evaluate, 1 recovered`; sections `*Failing (2)*`, `*Could not evaluate (1)*`, `*Recovered (1)*` in that order, 4 lines total |
| S3 | must | S; only recoveries | Only a `*Recovered (n)*` section; header `<project>: n recovered`; no empty groups |
| S4 | must | check `name: "<!channel> & <!here>"` fails | Its line holds `&lt;!channel&gt; &amp; &lt;!here&gt;`; no `<!` anywhere in the body |
| S5 | must | check `name: "<https://evil.example|click>"`; dataset `<@U123>`; owner `<!subteam^S1>`; a `failed_rows` message quoting `<b>` | Every `<`/`>`/`&` in those strings arrives escaped, in sections, context and `text`; the raw body contains no `<` at all |
| S6 | must | a check whose expression is `row_count > 0` | The line reads `row_count &gt; 0` in mrkdwn (shown as `>` in Slack) |
| S7 | must | a string already holding `&amp;` | Sent as `&amp;amp;` (shown literally) — escaping is not skipped for look-alike entities |
| S8 | must | history `fail`; this run `error` with a driver error quoting a row value | Line ends `: could not evaluate`; the error text appears nowhere in the body (D7) |
| S9 | must | a freshness check fails | `display_value` (the age) sits beside `message` (BACKLOG I-06, spec 007 Q4) |
| S10 | must | a check name of 1,000 `<` characters | Cut to 200 raw chars + `…`, then escaped; no `&lt` split mid-entity; the section ≤ 3,000 chars |
| S11 | must | 500 checks go `pass` → `fail` in one run | One POST; header `500 failing`; the section ≤ 3,000 chars and ends `…and N more failing` with N = 500 − lines shown; ≤ 6 blocks |
| S12 | must | the server answers 404 (`no_service`), 400 (`invalid_blocks`), 429, or times out | stderr `notifier 'sales-slack' could not send: HTTP 404` (or 400, 429, `timed out`); no body or URL logged; no retry; exit code unchanged |
| S13 | must | `url: https://hooks.slack.com/services/T/B/X` (a literal) | `validate` exits 3 with spec 018 N12's diagnostic at `file:line:col` |
| S14 | must | `channel: "#data"` under a slack notifier | `validate` exits 3: a Diagnostic at the key (unknown field), all such errors in one pass |
| S15 | must | `type: slak` | `notifier 'type' must be one of: webhook, slack` at the value |
| S16 | must | one check notifies a webhook and a slack notifier; slack answers 500 | The webhook still gets its POST (spec 018 N23); one warning naming `sales-slack` |
| S17 | must | `TW_SLACK` unset | Warning as spec 018 N11; `validate`, `list`, `compile` exit 0 |
| S18 | must | `examples/retail` with a slack notifier, run twice | First run one POST listing every planted defect under Failing; second run none |
| S19 | must | any body | No row values beyond `message`; no URL; no credentials; no link to `serve`; no `datasource` or file path anywhere |
| S20 | should | the JSON Schema for editors | Knows `type: slack` (`config/jsonschema.py`) |
| S21 | must | docs | `docs/check-language.md` "Notifications" gains `type: slack`, the layout, the escaping and size rules; README one line |
| S22 | should | an owner like `sales-data@example.com` or a message holding `example.com` | Sent with `verbatim: true`, so Slack does not auto-link it (Q2 confirms) |
| S23 | must | a plain comparison (e.g. `row_count > 0`) fails, with no `message` and no `owner` | Its line reads exactly `• <dataset> · row_count > 0: 0 rows` — no trailing separator, no empty parentheses |
| S24 | should | a group needs truncation and exactly one check is left over | Closing line reads `…and 1 more failing`, or for the error group `…and 1 more error` (singular, not `errors`) |
| S26 | must | a check `name: "@here @channel #general"` fails | The name arrives as written; the body has no `link_names` and no `parse` (D2) |
| S27 | must | a check name holding `\n*Recovered (9)*` and U+202E | One line; the newline and U+202E arrive as spaces (D3) |
| S28 | must | a project `name` of 200 characters | The header is ≤ 150 characters; `text` holds the full totals (D6) |
| S25 | must | two datasets of the same name on different datasources, one failing | Both lines read identically (dataset name only); not a false match — each is still evaluated and alerted under its own check id (`tablewatch history`, not the message, tells them apart), as the console already accepts |

## Non-goals

- Mentioning the owner (`<@U…>`), routing by owner, tag or severity; Teams, email: I-11.
- Links to `tablewatch serve` (no base URL is configured; would need a new setting).
- Slack apps, bot tokens, `chat.postMessage`, threads, message updates, interactivity, retries.
- A dependency on `slack_sdk`. Escaping `*`, `_`, `~` or `` ` `` in user strings (cosmetic, cannot ping; Q3).
- Changing the webhook payload or its `schema_version`.

## Decisions (REFINE: Q1, Q4 data-steward; Q2, Q3, Q5 security-reviewer)

- **D1 (Q1, Q4).** The wording and size rules above, as the data-steward settled them, including S23–S25.
- **D2 (Q2, R1–R2).** User strings go in `mrkdwn` with `verbatim: true` on every mrkdwn object (the
  context's too). They go through one `escape()` helper (`&`, then `<`, then `>`), and every
  interpolated value passes through it, including the project, run id and trigger. The header is
  `plain_text` with `emoji: false`. The body never sets `link_names` or `parse`. New scenario S26:
  a name of `@here @channel #general` arrives unchanged, and the body has no `link_names` or `parse` key.
- **D3 (R3).** Before cutting and escaping, C0/C1 controls (CR, LF, tab included) and the bidi
  controls U+202A–202E and U+2066–2069 become a space, so no string can add a line or reorder text (S27).
- **D4 (Q3, R4).** No host allowlist: spec 018 D6 holds (https anywhere, http only to loopback).
- **D5 (Q5, R5).** `fail` and `warn` messages are sent as written. The Slack renderer takes `message`
  only from `build_payload`, so D7's fixed `could not evaluate` holds. Revisit with I-30.
- **D6 (R6).** The header's text is cut to 150 characters (Slack's limit). `text` keeps the full
  totals. R7 is moot: the context block carries no paths (D1).
