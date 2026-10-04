# Iteration log

One entry per iteration, newest first. Written by the product-manager in the
REVIEW step; proposals needing the user's decision are also recorded here.

Each entry records: the spec, the PR, acceptance results, reviewer findings
and how they were resolved, what was deferred, and what was learned.

Older entries (iterations 1–28) are in
[`archive/iterations-01-28.md`](archive/iterations-01-28.md); planners
read only the latest entry here.

## Iteration 31 — Postgres results store, part 1: verified in CI, shared safely (I-14 part 1), 2026-10-04

- **Spec:** [031-postgres-results-store](specs/031-postgres-results-store.md). **Branch:**
  `iter/031`. Full track. No items added (freeze). The owner chose this iteration directly
  ("Lets do I-14", 2026-10-04); the run stops after it.
- **REFINE.** Security Q1–Q3: a throwaway CI password, not `trust`; digest-pinned images; `${env:}`
  resolved per URL part. Architect Q4–Q6: check-first migrate (a read-only role can still read);
  an advisory lock bounded by a 60s `lock_timeout`; revision 0003 widens unindexed columns to
  `Text`. Data-steward Q7: control characters refused at load, a data NUL becomes U+FFFD at save.
- **Shipped:** a `postgres` CI job (15.19, 18.6, digest-pinned) runs every store test; `${env:}`
  in `results.url`, resolved only on open; a cross-process advisory lock around `upgrade head`;
  reads never migrate; SQLSTATE-classified store errors; a README "shared results store" section.
  One BUILD defect fixed: a check-id prefix matched case-insensitively on SQLite only.
- **Reviewer findings and resolution:**
  - *architect — approve*; 6 follow-ups fixed (`49990b9`): a project-name cap, `NewerStoreError`,
    a shared `_sqlstate` helper, `notify` reading without creating a store.
  - *security — approve*; 2 fixed (`daedbd3`): `${env:}` in a URL's user part was split at its
    own `:`, fixed by parsing references as tokens; a driver hint behind a whole-URL variable.
  - *qa-engineer — fail, then fixed; 31 tests.* Blocker (`bb88540`): an upgrade's first run
    skipped every `change()` check (reads refused any older store); now accepted since 0002.
    Also fixed: project-name control characters; two SQLSTATE reasons; every store test file now
    runs on Postgres.
  - *data-steward — accept*, 20/21 must + 2/2 should, live on Postgres 18. 2 fixed (`90d1267`): an
    unmatched SQLSTATE no longer says "could not connect"; README wording.
- **Not added (backlog freeze):** none beyond I-14's own remaining scope.
- **Lesson:** refusing any store the code does not fully recognise sounds safe, but it silently
  broke a working feature the first run after an upgrade — check a safety rule against every reader.
- **Backlog:** I-14 stays in progress — part 1 done; part 2 (the two indexes, the 1M-result
  `/checks` measurement gating I-23) is next, but needs the owner: this was a direct pick, not a
  continued run, alongside I-07 part 3, I-13 part 2 and I-08's `sql_metric`.

## Iteration 30 — Loader wording, a percent written as a fraction, console rows told apart (I-28, I-45), 2026-10-04

- **Spec:** [030-loader-wording-console-datasource](specs/030-loader-wording-console-datasource.md).
  **Branch:** `iter/030`. Light track; REVIEW by the tech lead. No items added (freeze).
- **Decisions (tech lead):** Q1, the fraction warning sits at the check; Q2, alike console rows
  are told apart by their source location, the one suffix that separates every collision.
- **Shipped:** a bare number strictly between 0 and 1 on a `*_percent` metric warns (`0.05 on
  missing_percent means 0.05%, not 5% …`), in a condition, `between` or a trigger, at `validate`
  and `run`. Loader wording: "an integer"; a list of only bare `-` items is one "is empty" error; an
  explicit `id:` used twice says the id is already used; two `schema` checks are told to merge
  their lists; a bad `where:` no longer adds a phantom "duplicate check". `validate` says "1
  dataset, 1 check". The console adds a DATASOURCE column only when a run spans more than one,
  and rows that still read alike get ` (checks/a.yml:5)`. JSON, JUnit, the report, the API, ids
  and exit codes are unchanged. Suite: **2481 passed, 1 skipped, 16 xfailed**.
- **Reviewer findings and resolution:**
  - *qa-engineer — pass-with-followups, no blockers; 24 tests, 3 strict xfails, all fixed
    (a9a2413).* Names that clip to the same cell now get the location; the warning's two figures
    agree; a tiny fraction's suggestion is plain decimals that parse (not `1e-06%`). A
    `--connect` assertion in the builder's tests that could not fail was removed. L11 ids and C6
    JSON/JUnit pinned against `main`.
  - *data-steward — stalled twice (watchdog); acceptance finished by the tech lead per PROCESS.md*,
    running L1, C1–C3 and the one-datasource table through the CLI: messages and table as specified.
    Deviation accepted: L1 says "for 5 percent", not "five percent" (figures, not words, for any value).
- **Not added (backlog freeze):** none.
- **Lesson:** ten older tests pinned the old wording; a wording item is cheap to build but touches
  every test that quotes a message — grep the tests for each changed string before the first run.
- **Backlog:** I-28 and I-45 done. **The owner's run ends here** (iterations 15–30); the next
  candidates (I-07 part 3, I-13 part 2, I-08's `sql_metric`) each need a decision, and I-14 waits
  on the owner.

## Iteration 29 — Files as datasets, part 2: glob patterns and `schema` on files (I-08 part 2), 2026-10-03

- **Spec:** [029-files-globs-schema](specs/029-files-globs-schema.md). **Branch:** `iter/029`.
  Full track. No items added (freeze).
- **REFINE.** Architect → Q1–Q2: one `expand(root, pattern)` called only from `swap_path`, binding
  the list of absolute paths, matches cached per pattern per run; `FileSource.schema_statement()`
  via `DESCRIBE`, passing the one-`SELECT` gate. Security → Q3–Q4: the walk uses `os.scandir`/
  `lstat`, never entering a symlinked directory; a symlink anywhere among the matches refuses the
  whole dataset; a match whose own name holds a pattern character is refused too (G14); caps on
  matches, `**` depth and entries scanned; `allowed_directories` as the read-time backstop.
  Data-steward → Q5–Q6: files are unified by column name (`union_by_name`), a column missing from
  one file reads NULL rather than erroring; messages name the pattern and datasource, never a
  matched file or DuckDB's own text.
- **Shipped:** a files dataset may be a glob (`*`, `?`, `[ ]`, `**`, any depth); tablewatch expands
  it in Python inside root, checks every match against part 1's inside/symlink rule, sorts them and
  hands DuckDB the list — DuckDB never globs. `schema` now works on a file or a pattern, reading
  DuckDB's column list through `DESCRIBE` without reading rows beyond its own type-detection sample.
  Suite: **2435 passed, 1 skipped, 16 xfailed**.
- **Reviewer findings and resolution:**
  - *security-reviewer — approve-with-followups; fixed.* A file vanishing mid-walk leaked its
    absolute path in the refusal; now skipped silently (9258a77). Consecutive `**` segments caused
    a RecursionError; collapsed (9258a77). Repeated `**/*` routes made the walk combinatorial; fixed
    with a (folder, rest-of-pattern) memo so each is walked once (eb1ebe7). Accepted: a metadata-only
    `stat` of a link target under `**`, and that a segment starting with `.` matches hidden names.
  - *qa-engineer — pass, no blockers; 59 tests plus 4 strict xfails, all fixed (a790b3a).* An
    unrelated file symlink under `**` no longer refuses the dataset; a literal `.hidden/` segment is
    now entered; the entry cap counts each entry once; names are compared in NFC.
  - *data-steward — accept; 22/23 scenarios run via the CLI, G16 checked by inspection.*
    Non-blocking: the editor's JSON Schema did not say a files dataset may be a pattern; fixed
    (9e57b93).
- **Not added (backlog freeze):** none beyond I-08's own remaining scope.
- **Lesson:** expanding the glob in Python, not DuckDB, moved every denial-of-service question
  (deep `**`, huge match counts, repeated route explosion, a file vanishing mid-walk) onto
  tablewatch's own walk — each is a cost the walk has to bound itself, not one DuckDB's own glob
  would have hit.
- **Backlog:** I-08 stays in progress — glob patterns and `schema` on files are done; a
  `sql_metric` naming its own file remains (needs a language decision on how a query names its
  dataset). Next: iteration 30, I-28 with I-45, as planned in iteration 25.
