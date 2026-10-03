# Spec 025: `serve` polish — a usable startup URL, JSON stderr, no server paths, the 503 envelope (I-20)

- **Track:** full — a wire contract (messages served over `/api/v1`, the 503 body), security
  triggers (an inbound network surface, what the API exposes), and serve's exit-code paragraph.
- **Size:** S. Pre-planned split: if REFINE finds S5 (the connection limit) needs more than one
  ASGI wrapper, S5 stays in I-20 as part 2 and this spec ships S1–S4, S6–S9.
- **Reviewers:** qa-engineer, data-steward, security-reviewer (REFINE), architect (REFINE).
- **Item:** I-20 (rank 15, 1.6). Folds in "not added" from iteration 22 (serve's exit code on an
  unreadable store) and the notes already on I-20 (COOP warning, iteration 5; the SIGTERM flake,
  iterations 4 and 20).

## Problem and persona

Priya (platform engineer) runs `tablewatch serve` on a shared box for her team. Today the
startup line says `http://0.0.0.0:53019/`, which no browser can open; under `--log-format json`
her log shipper gets two plain-text lines among the JSON; an `error` result served to the UI
shows `IO Error: Cannot open database "/srv/dq/retail/missing.duckdb" …`, the server's own
folder layout; and past 64 connections uvicorn answers a plain-text 503 that her client cannot
parse. She copes by editing the URL by hand and filtering non-JSON lines. Dana (data engineer)
reloads the UI and re-downloads the whole bundle every time, because hashed assets are `no-store`.

Measured on `2178204` (retail example, a copy with `path: missing.duckdb`): S1, S2, S3, S5, S6
reproduce as described in their "today" column; the 503 is the strict xfail
`tests/test_server_adversarial.py::test_connection_limit_answers_with_the_error_envelope`.

Research: Vite prints `Local:` and one `Network:` line per interface for `--host 0.0.0.0`
([vite.dev/config/server-options](https://vite.dev/config/server-options)); Python's stdlib has no
interface list without a dependency, so we print a loopback URL and say what the bind means.

## Scenarios

`R` = the retail example; `M` = a copy with `datasources.lake.path: missing.duckdb`, run once.

| id | | given | expected |
| --- | --- | --- | --- |
| S1 | must | `R`: `serve --host 0.0.0.0 --port 8765` | stderr startup line: `tablewatch serve: http://127.0.0.1:8765/ (listening on all IPv4 addresses; project retail-example, 19 checks; API at /api/v1)`. Today: `http://0.0.0.0:8765/` |
| S2 | must | `R`: `serve --host :: --port 8765` | `tablewatch serve: http://[::1]:8765/ (listening on all IPv6 addresses; project retail-example, 19 checks; API at /api/v1)`. Today: `http://[::]:8765/` |
| S3 | must | `R`: `serve --host 127.0.0.1` and `--host 192.168.1.5` | unchanged: the bound address as given (`http://192.168.1.5:8765/ (project …)`) |
| S4 | must | `R`: `--log-format json serve --host 0.0.0.0` (non-loopback warning, startup line, access log), and a project with one diagnostic error | **every** stderr line parses as a JSON object with `time`, `level`, `logger`, `message`; the warning is `level: warning`, the startup line `level: info`, each diagnostic `level: error` with its `file:line:col` in `message`. Today: the warning and startup lines are plain text |
| S4b | must | `--log-format json serve` with a failure to start (port in use; store unreadable; server extra missing) | the one-line reason is a JSON object, `level: error`; exit code unchanged (3) |
| S4c | must | `--log-format text serve` (default) | byte-for-byte today's lines (no `WARNING tablewatch:` prefix added) |
| S5 | must | `R` served; 64 requests **in flight** (a blocked handler, ASGI-level test), then `GET /api/v1/project` (D4) | `503`, `content-type: application/json`, every header in `SECURITY_HEADERS`, body `{"error": {"code": "unavailable", "message": "the server is busy — try again shortly"}}`. Today: uvicorn's plain-text 503 (the strict xfail flips to a passing test) |
| S5b | must | as S5, then the 64 requests finish | the next `GET /api/v1/project` is `200` |
| S5c | should | more than 256 connections (idle sockets) | uvicorn's backstop answers its own plain-text 503; documented (D4) |
| S6 | must | `M` served: `GET /api/v1/checks`, `/checks/{id}`, `/checks/{id}/history`, `/runs/{id}` for the errored checks | `message` is `IO Error: Cannot open database "missing.duckdb" in read-only mode: database does not exist` — the project root prefix removed, path shown project-relative. Today: the absolute path `/…/p/missing.duckdb` |
| S6b | must | as S6, with a datasource path **outside** the project (`path: /data/shared/x.duckdb`, missing) | the outside path is shown as `<outside the project>/x.duckdb` (wording: Q2); no absolute directory appears in any `/api/v1` body |
| S6c | must | as S6, results recorded **before** this change | scrubbed the same way when served: the rule applies at serve time, not at record time; the store keeps the text as recorded |
| S6d | must | `M`: `tablewatch run` and `tablewatch history <id>` on the CLI | unchanged: the local user sees the full path (non-goal N2) |
| S6e | should | a project diagnostic that names an absolute path (e.g. a files `root` outside the project) served on `/api/v1/project` | the same scrub as S6/S6b |
| S7 | should | `R` served: `GET /assets/index-<hash>.js` | `cache-control: public, max-age=31536000, immutable`; every other security header unchanged. `GET /` and `/api/v1/*` stay `no-store`. Today: `no-store` |
| S7b | should | `GET /assets/does-not-exist-abc123.js` | the 404 stays `no-store` |
| S8 | should | `R`: `serve --host 0.0.0.0`, opened from another machine over `http` | no Chromium console warning about `Cross-Origin-Opener-Policy` on an untrustworthy origin (the header is sent only where it has effect, or kept: Q4). Today: the warning appears |
| S9 | must | `R` with `.tablewatch/results.db` at mode `000`: `serve` | `tablewatch: results store: could not be opened — run with -v for details`, exit **3** (kept: Q1), and README/`cli/main.py` docstrings say why `serve` differs from `runs`/`history`/`report` (2) |
| S10 | should | `tests/test_server.py::test_sigterm_stops_serve_cleanly` | passes 50 of 50 runs in a loop (`pytest --count` or a shell loop); a cause found and fixed, not a retry |

## Non-goals

- N1: listing every network interface (needs a dependency or a DNS lookup); printing the hostname.
- N2: scrubbing paths on the CLI (`run`, `history`, `test-connection`) or in the store; this is
  what the server exposes, not what the local user sees.
- N3: raising the connection limit, rate limiting, or authentication (Phase 4).
- N4: changing the meaning of any exit code; changing serve's codes at all (see Q1).
- N5: TLS or reverse-proxy headers (`proxy_headers` stays off).
- N6: the unlabelled probe columns in the SQL section (iteration 24, not added): C4, not C1.

## Decisions

- **D1 (Q1; tech lead).** Kept: `serve` exits 3 on a store it cannot open, as the README and the
  `cli/main.py` docstring already document ("3 when it could not start"). No contract change.
- **D2 (Q5; data-steward).** The parenthesis reads `(listening on all IPv4 addresses; project
  <name>, <n> checks; API at /api/v1)` for `0.0.0.0`, and `(listening on all IPv6 addresses; …)`
  for `::` — "IPv4"/"IPv6" named explicitly each time, not "all addresses", because Priya is
  choosing a bind and needs to know which family it opens; S3's single-address bind stays
  unchanged (no "listening on" clause — the address alone already says what's reachable). The
  503 body's code is `unavailable`, matching the snake_case, condition-naming style of
  `not_found`/`forbidden_host`/`internal_error` (a mood word like `busy` fits the message, not
  the machine-read code). The message stays `the server is busy — try again shortly`: "busy"
  names the cause in Priya's terms (a connection limit, not a crash) and "try again shortly" is
  the one action a client or a human watching logs can take, matching the em-dash,
  no-full-stop style of `FORBIDDEN_HOST`/`INTERNAL_ERROR`.
- **D3 (Q2, security R1–R3).** One pure helper outside `server/` (`tablewatch/paths.py`), applied in
  `server/schemas.py` to every result `message` and `Diagnostic.message`. It strips the current root's
  prefix first (as given, resolved, and macOS `/private` forms; longest first), so those paths read
  project-relative. Any other absolute path (POSIX, `C:\`/`C:/`, UNC, `file://`, `~`, `~user`) becomes
  `<outside the project>/<last segment>`. A test walks every `/api/v1` body for an in-root, an outside and
  a `~` path. `report` is not changed here.
- **D4 (Q3, architect + security R4–R6).** An in-flight request counter inside `_Guard`, after the Host
  check, decremented in `finally`. Past 64 it answers through `send_secured`: the JSON envelope plus
  every security header. uvicorn's `limit_concurrency` becomes a 256 backstop, never `None`, and its
  plain-text 503 is documented. Idle sockets are not counted (uvicorn arms keep-alive only after a
  response); this is recorded as a Phase 4 note on I-20.
- **D5 (Q4, R7).** COOP is sent only when the request's `Host` is loopback or `localhost`
  (`server/hosts.py`'s rule); every other security header stays on every response. A code comment says
  COOP returns with TLS or a proxy (Phase 4).
- **D6 (Q6, architect).** `logs.py` gains a `tablewatch.console` logger configured by `configure()`:
  `%(message)s` in text mode (S4c byte-identical) and `JSONFormatter` in json mode, pinned at INFO and
  independent of `-v`/`-q`. Every command's stderr lines (`_fail`, `_project`, serve's own) go through
  it; stdout is untouched. The wildcard-to-loopback URL logic moves to `server/hosts.py` as a pure
  function.
