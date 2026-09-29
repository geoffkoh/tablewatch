# Spec 010: A broken check file is a diagnostic, never a traceback

| | |
| --- | --- |
| Backlog item | I-36 (architect F3, iteration 6 REFINE; qa-engineer, iteration 6 VERIFY; widened in iteration 6 REVIEW; next by iteration 9 REVIEW) |
| Features | A, E0 (hardening) |
| Phase | 2 (`0.2.0`) |
| Size | S |
| Depends on | nothing |
| Branch | `iter/010-loader-tracebacks` |
| Status | **shipped** (iteration 10, PR #15, 2026-09-29). REFINE settled 2026-09-28 (data-steward on Q2; architect on Q1 and Q4; the PM settled Q3 — see "Open questions", now settled). Planned in iteration 10 PLAN, 2026-09-28, against `main` at `37a2004`. Every "today" output below was measured on `main` with `tablewatch validate`; every "after" output was measured with a throwaway prototype, then confirmed on the build by the data-steward through the real CLI (23/23) |

## Problem and persona

**Dana, data engineer**, pasted a check from a wiki page. The page held
an invisible form feed (`\x0c`) in a comment. `tablewatch validate` in
CI printed a 40-line Python traceback ending in:

```text
ruamel.yaml.reader.ReaderError: unacceptable character #x000c: special characters are not allowed
  in "<unicode string>", position 28
exit=1
```

No file name, no line. She cannot see the character in her editor. Worse,
**exit 1 means "a check failed"** in the exit-code contract
(`cli/main.py`): her orchestrator reads a broken file as bad data, and
nothing else in the project ran. Design rule 5 ("every user mistake is a
`Diagnostic` at `file:line:col`, … never raise from a check file") is
broken.

**Priya, analytics engineer**, keeps her check files DRY with YAML
anchors and merge keys, which tablewatch already accepts for options
(spec 008) and for a root `filter:` (iteration 6):

```yaml
dataset: orders
checks:
  - row_count:
      <<: &base {warn: when < 5}
```

`validate` crashes (`TypeError: cannot unpack non-iterable NoneType
object`, exit 1). The backlog recorded this as a `KeyError`; iteration 8
moved the crash, it did not remove it.

How they cope today: bisect the file by hand, or stop using `<<:`.

### The sweep (measured on `37a2004`)

Every row is a traceback with **exit 1** today. The three families are
all in scope: each is a check file, `_defaults.yml` or `tablewatch.yml`
that the loader cannot turn into a diagnostic.

| Family | Trigger (any YAML file the loader reads) | Exception today |
| --- | --- | --- |
| T. Unreadable text | a character YAML forbids: C0 controls other than tab/LF/CR (`\x00`, `\x07`, `\x0b`, `\x0c`, `\x1c`–`\x1e`, …), `\x7f`, C1 controls U+0080–U+009F other than NEL (U+0092 is what a Windows-1252 `’` becomes when converted as Latin-1), U+FFFE/U+FFFF | `ruamel.yaml.reader.ReaderError` (a `YAMLError`, not a `MarkedYAMLError`) |
| T. | bytes that are not UTF-8 (a Latin-1 `é`, a UTF-16 file) | `UnicodeDecodeError` from `read_text` (only `OSError` is caught) |
| G. Tagged values | an explicit core tag ruamel cannot construct: `!!int xyz`, `!!float xyz`, `!!bool xyz`, `!!int 0x`, `!!omap x`, `!!set x` | bare `ValueError` / `KeyError` / `IndexError` / `AttributeError` from ruamel's constructor |
| M. Merge keys | a `<<:` merge that brings in a key the loader locates: in a check's options (`warn`, `fail`, and when invalid `name`, `id`, or any unknown option); the check item itself (`- <<: {row_count > 0: {}}`); a check file's root (`dataset`, `datasource`, `tags`, `checks`); `_defaults.yml` (invalid or unknown keys); `tablewatch.yml` (any setting pydantic rejects) | `TypeError` from `node.lc.value/key` returning `None`, or `KeyError` |

Swept and **not** crashing (no change): duplicate keys, complex and
non-string keys, recursive aliases, `!!python/…` and custom tags,
`!!binary`, `!!timestamp` with bad text (already a diagnostic), a BOM,
bare-CR and CRLF line ends, NEL/U+2028, deep parentheses and huge
numbers in expressions, symlink loops and self-links under `checks/`, an
empty or non-mapping `tablewatch.yml`. A merged valid `name:`, `where:`,
`filter:` or value list already loads.

### What others do

Other tools stop at the parser's message. PyYAML and ruamel report a
`ReaderError` as a character offset ("position 28"), not a line; yamllint
reports it as a syntax error at `line:col`
([yamllint rules](https://yamllint.readthedocs.io/en/stable/rules.html)).
dbt and Soda surface the parser's message with the file name. The YAML
1.2 spec forbids these characters outright
([YAML 1.2.2, 5.1 Character Set](https://yaml.org/spec/1.2.2/#51-character-set)),
and supports merge keys only as a 1.1-era type
([merge key type](https://yaml.org/type/merge.html)). tablewatch already
honours merges; this spec makes it do so everywhere, not in some places.

## Outcome

Any file the loader reads (check file, `_defaults.yml`, `tablewatch.yml`)
that it cannot parse produces a `Diagnostic` at `file:line:col` and exit
3 from `validate`, `list`, `compile` and `run` — never a traceback, never
exit 1. Other files still load in the same pass. Merged keys load as
written everywhere; a problem in merged content is reported where it is
written, inside the merged mapping.

## Acceptance scenarios

The project for every scenario: `tablewatch.yml` is

```yaml
name: p
datasources:
  wh:
    type: duckdb
    path: wh.duckdb
```

and the file under test is `checks/orders.yml` unless named. `\x0c` etc.
mean the raw byte in the file. Closing summary lines are omitted where
they only restate the count ("tablewatch: 0 datasets, 0 checks — 1
error").

### T — unreadable text

**Message format (Q2, data-steward).** A forbidden character is
reported as

```text
invalid YAML: hidden control character U+XXXX (<name>) is not allowed; delete it
```

- `hidden` because the user cannot see it: that is the whole difficulty
  of this mistake, and it tells Dana to look at the column, not the text.
- `(<name>)` for the characters people actually paste, and only those:
  U+0008 `backspace`, U+000B `vertical tab` (Word's Shift+Enter line
  break), U+000C `form feed` (a PDF or wiki page break), U+001B `escape`
  (terminal colour codes), U+007F `delete`. Every other C0/C1 control has
  no parenthesis: `hidden control character U+001C is not allowed; delete it`.
  A name we would have to look up is noise; the code point is enough to
  search for.
- U+0000 is almost always a UTF-16 file without a BOM, not a stray
  character (every ASCII character decodes as itself plus a NUL), so it
  says so: `invalid YAML: character U+0000 (null) is not allowed; the file
  may be UTF-16 — save it as UTF-8`.
- U+FFFE / U+FFFF are not controls: `invalid YAML: character U+FFFE is
  not allowed; delete it`.
- `invalid YAML:` stays as the prefix, like every other YAML diagnostic.

**T1 (must) — the reported case.** Given

```text
dataset: orders
# a comment \x0c here
checks:
  - row_count > 0
```

When `tablewatch validate`, then exactly one diagnostic and exit 3:

```text
checks/orders.yml:2:13: error: invalid YAML: hidden control character U+000C (form feed) is not allowed; delete it
```

(today: `ReaderError` traceback, exit 1). Parametrised over the byte in
place of `\x0c`, all at `2:13`:

| Byte(s) in the file | Message after `invalid YAML: ` |
| --- | --- |
| `\x0b` | `hidden control character U+000B (vertical tab) is not allowed; delete it` |
| `\x08` | `hidden control character U+0008 (backspace) is not allowed; delete it` |
| `\x1b` | `hidden control character U+001B (escape) is not allowed; delete it` |
| `\x7f` | `hidden control character U+007F (delete) is not allowed; delete it` |
| `\x07`, `\x1c`, `\x1d`, `\x1e` | `hidden control character U+0007 is not allowed; delete it` (and so on, no name) |
| `\xc2\x92` (UTF-8 for U+0092) | `hidden control character U+0092 is not allowed; delete it` |
| `\x00` | `character U+0000 (null) is not allowed; the file may be UTF-16 — save it as UTF-8` |

**T1b (must) — Windows line ends.** T1's file with CRLF line ends (as
Notepad saves it) gives the same diagnostic at `2:13`: the position is
counted over the text after universal-newline reading, as every other
position is.

**T2 (must) — the column counts characters, not bytes.** Given
`dataset: é orders` on line 1 and `# é \x0c` on line 2: `2:5` (ruamel's
`position` is a character index into the text; a byte offset read as a
character index would say `2:7`).

**T3 (must) — inside a value, on a later line.** Given

```text
dataset: orders
checks:
  - row_count > 0:
      name: "a\x0bb"
```

then `checks/orders.yml:4:15: error: invalid YAML: hidden control character U+000B (vertical tab) is not allowed; delete it`.
(A *written escape* `"a\fb"` is legal YAML and keeps loading.)

**T4 (must) — U+FFFE.** `# a ￾ b` (UTF-8 bytes `EF BF BE`) on line
2 gives `checks/orders.yml:2:5: error: invalid YAML: character U+FFFE is not allowed; delete it`.

**T4b (should) — a UTF-16 file without a BOM.** `dataset: orders`
saved as UTF-16LE with no BOM (every ASCII byte followed by `00`) gives
`checks/orders.yml:1:2: error: invalid YAML: character U+0000 (null) is not allowed; the file may be UTF-16 — save it as UTF-8`,
exit 3. (Measured: the bytes decode as UTF-8, and ruamel stops at
position 1.)

**T5 (must) — not UTF-8.** Given line 2 `# caf\xe9` (Latin-1 bytes):

```text
checks/orders.yml:2:6: error: not UTF-8 text: byte 0xE9 cannot be decoded; save the file as UTF-8
```

Line and column count the decoded characters before the bad byte. The
same file with CRLF line ends (Notepad "ANSI") and `# it\x92s` (a
Windows-1252 `’` pasted from Word or Outlook) gives
`checks/orders.yml:2:5: error: not UTF-8 text: byte 0x92 cannot be decoded; save the file as UTF-8` —
CRLF must not count as two characters.

The message names no editor or product (Q2): Excel does not write YAML
files, and "Notepad" or "Windows-1252" would be wrong as often as right.
"save the file as UTF-8" is the one action every editor offers.

**T5b (should) — UTF-16 with a BOM.** A file that starts `FF FE`
(Windows PowerShell 5.1 `>` and `Out-File`, Notepad "Unicode") or
`FE FF` (macOS `iconv -t utf-16`) gives
`checks/orders.yml:1:1: error: not UTF-8 text: the file is UTF-16; save it as UTF-8`.
Must, as a floor: without the special case it gives the T5 message
naming `0xFF` or `0xFE` at `1:1`, never a traceback.

**T6 (must) — the other files.** `_defaults.yml` containing
`owner: a\x0cb` gives `checks/_defaults.yml:1:9: error: invalid YAML: hidden control character U+000C (form feed) …`,
exit 3. `tablewatch.yml` with `# \x0c` on line 2 gives
`tablewatch.yml:2:3: error: invalid YAML: hidden control character U+000C (form feed) …`, exit 3;
with `name: caf\xe9` gives `tablewatch.yml:1:10: error: not UTF-8 text: byte 0xE9 …`, exit 3.

**T7 (must) — one pass.** T1's file saved as `checks/zz_broken.yml`
beside a good `checks/orders.yml` (`row_count > 0`): `validate` reports
the T1 diagnostic for `zz_broken.yml` **and** loads `orders` (1 dataset,
1 check); exit 3. `run` reports the same diagnostic and exit 3 (nothing
runs on a broken project, as today for invalid YAML).

**T8 (must) — no regression.** A UTF-8 BOM, CRLF and bare-CR line ends,
and a tab in a comment keep loading exactly as today.

### G — tagged values ruamel cannot construct

**G1 (must).** Given

```yaml
dataset: orders
checks:
  - duplicate_count(a) = 0:
      name: !!int xyz
```

then `checks/orders.yml:4:13: error: invalid YAML: 'xyz' is not a valid !!int`,
exit 3 (today: `ValueError` traceback, exit 1). The position is the tag,
where ruamel already puts its own `!!timestamp` error. Same shape for
`!!float xyz` and `!!bool xyz` (`… is not a valid !!float` / `!!bool`,
`4:13`).

**G2 (should).** `!!int 0x`, `!!omap x` and `!!set x` give a diagnostic
at their tag too. Any other exception out of `yaml.load` that cannot be
located gives `invalid YAML: …` at `1:1` of that file — never a
traceback (must).

**G3 (must) — the other files.** `tablewatch.yml` with
`wh: {type: postgres, host: h, database: d, port: !!int x}` on line 3
gives `tablewatch.yml:3:52: error: invalid YAML: 'x' is not a valid !!int`;
`_defaults.yml` `owner: !!int x` gives `checks/_defaults.yml:1:8: …`.

### M — merge keys

**M1 (must) — the reported case loads.** Priya's file above: `validate`
exit 0, "1 datasets, 1 checks — no problems found"; `run` on a one-row
`orders` gives `WARN orders row_count | warn when < 5  1`, exit 0.
`<<: {fail: when < 5}` likewise loads.

**M1b (must) — shared triggers, the way teams write them.** Given

```yaml
dataset: orders
checks:
  - missing_percent(email):
      <<: &nulls {warn: when > 1%, fail: when > 5%}
  - missing_percent(phone):
      <<: *nulls
  - missing_percent(postcode):
      <<: *nulls
      fail: when > 20%
```

`validate` exits 0 with 3 checks (today: `TypeError` traceback, exit 1),
and `list` shows three checks, `postcode`'s with its own `fail:`. A
mistake inside the anchor (`warn: when > 1d`) is reported where it is
written, `checks/orders.yml:4:25: error: '1d' is a duration, but missing_percent is not`,
once per check that merges it (three identical lines), exit 3 — as an
aliased options mapping is reported today (measured).

**M7 (must) — a merge does not change a check's id.** The `email` check
in M1b has the same id in `tablewatch list` as the same check with
`warn: when > 1%` and `fail: when > 5%` written directly. (The triggers
feed the id through the canonical expression; a merged `where:` already
gives the same id today — measured.) Otherwise moving triggers into an
anchor would silently start a new history.

**M2 (must) — a mistake in merged content is placed where it is
written.** Each file is the M1 file with line 4 replaced; exit 3; one
diagnostic:

| Line 4 | Diagnostic |
| --- | --- |
| `      <<: {warn: 5}` | `checks/orders.yml:4:18: error: \`warn:\` takes a trigger such as 'when < 10'` |
| `      <<: {warn: when <<}` | `checks/orders.yml:4:24: error: expected a number, found '<'` |
| `      <<: {bogus: 1}` (check `row_count > 0:`) | `checks/orders.yml:4:12: error: unknown option for row_count 'bogus'` |
| `      <<: {name: 5}` (check `row_count > 0:`) | `checks/orders.yml:4:18: error: \`name:\` must be a non-empty string` |
| `      <<: {id: "a b"}` (check `row_count > 0:`) | `checks/orders.yml:4:16: error: invalid id 'a b' — use letters, digits, '.', '_', ':' or '-'` |

**M3 (must) — the check item and the file root.**

- `checks:` then `  - <<: {row_count > 0: {}}` loads one check and
  runs it (PASS on one row).
- A root `<<: {dataset: orders, checks: [row_count > 0]}` loads and runs.
- Root `<<: {tags: 5}` (then `dataset:`/`checks:`) gives
  `checks/orders.yml:1:12: error: \`tags:\` must be a string or a list of strings`.
- Root `<<: {checks: 5}` gives `checks/orders.yml:1:14: error: \`checks:\` must be a list`.
- Root `<<: {datasource: nope}` gives
  `checks/orders.yml:1:18: error: unknown datasource 'nope' (defined in tablewatch.yml: wh)`.

**M4 (must) — `_defaults.yml`.** `<<: {owner: 5}` gives
`checks/_defaults.yml:1:13: error: \`owner:\` must be a non-empty string`;
`<<: {bogus: 5}` gives `checks/_defaults.yml:1:6: error: unknown setting in _defaults 'bogus'`;
`<<: {owner: dana, tags: [a]}` loads and is inherited.

**M5 (must) — `tablewatch.yml`.** `<<: {name: 5}` on line 1 gives
`tablewatch.yml:1:12: error: name: Input should be a valid string`.
`    <<: {type: duckdb, path: 5, bogus: 1}` under `datasources: wh:` (line
4) gives both, in one pass:

```text
tablewatch.yml:4:30: error: path: Input should be a valid string
tablewatch.yml:4:40: error: unknown setting 'bogus'
```

(`unknown setting` points at the value, as it does today for a key
written directly.)

**M6 (must) — own keys win, and are located as their own.** `warn:`
written in the item beside a `<<:` that also has `warn:` uses the
item's own (YAML merge rule), and a mistake in it is reported at the
item's own line. `<<: [*a, *b]` with the key in both: the first merged
mapping's value is used and located (ruamel's order).

### X — every entry point

**X1 (must).** For one T, one G and one M case, `validate`, `list`,
`compile` and `run` each exit 3 with the diagnostic, and
`tablewatch.load()` returns a `Project` with the diagnostic and
`ok is False` rather than raising. A `tablewatch.yml` case raises
`ProjectError` with the diagnostic, as `load()` does today for invalid
YAML there.

**X2 (should).** A property test: random bytes inserted at a random
offset of the retail example's check files never make `load()` raise
anything but `ProjectError` (for `tablewatch.yml`), and never make
`validate` exit 1.

## Non-goals

- New YAML features, or rejecting merge keys. Merges already work in
  places; this makes them work in all.
- Friendlier text for errors that are already diagnostics (`invalid
  YAML: expected <block end>…`); loader wording is I-28.
- Encodings other than UTF-8. We say "save it as UTF-8", we do not
  guess.
- Runtime crashes after loading (I-42) and CLI file/store errors
  (I-17).
- `x-`-prefixed "hidden" keys in `tablewatch.yml` to hold anchors
  (a new feature; listed as "not added").
- Other misleading-but-not-crashing results found in the sweep (below,
  "found and not in scope").

## Design notes

- **Rule 5** is the whole point; **rule 7's exit codes** are the harm
  today (a traceback exits 1, "fail"). No rule is bent.
- **One layered catch in `YAMLSource.load` (settled in REFINE, Q4).**
  In order: `read_bytes`; a UTF-16/UTF-32 byte-order-mark check (T5b,
  the encoding named); decode the whole file as UTF-8 and, on
  `UnicodeDecodeError`, place the diagnostic from `exc.start` over the
  decoded prefix (T5); universal newlines applied by hand, identical to
  `read_text`, so every existing position holds (T8, T1b); then
  `ReaderError` (character index → line/col) → `MarkedYAMLError` (as
  today) → any other `Exception` from `yaml.load`, treated as the file's
  fault (a third-party parser over user text). Only the catch-all runs
  the tag locator (G), and it logs the original exception at debug
  level so a genuine ruamel bug stays findable.
- **One merge-aware resolver, `_owner` (settled in REFINE, Q1).** It
  looks in the mapping's own `lc.data`, then in `node.merge`,
  recursively, and never returns a mapping that does not hold the key.
  `of_key` / `of_value` go through it, so every call site is safe;
  `of_value_or_node` is deleted. `of_own_key` (own keys only) serves
  `_own_key_line`, so a merged `filter:` keeps `filter_line` `None`
  (spec 006). `locate()` in `tablewatch.yml` uses the same lookup. No
  caller relied on the `KeyError`.
- **G's position (settled, Q3: G1 stays a must, exact positions).**
  Compose the text (composing does not construct), walk the nodes, and
  report the first explicitly tagged node that fails to construct, at
  its tag. Built as: one iterative node walker (`walk_nodes`, shared
  with `spans.py`, with a visited set so an alias cycle cannot recurse);
  innermost node first; the value shown is built from the composed tree
  and shortened when long. Verbatim `!<tag:…>` and `%TAG` shorthand tags,
  and nesting deeper than about 250 levels, fall back to `1:1` (allowed
  by G2).
- Tests: most scenarios are loader tests with no database; M1, M3 and
  X1's `run` on DuckDB and SQLite (a `run` touches a backend).
- Check identity is untouched: nothing here feeds `derive_check_id`.

**Open questions for REFINE — all settled**

1. (tech lead / architect) Merge-aware `of_key`/`of_value` everywhere,
   versus a separate lookup at each call site. **Settled:** one
   merge-aware resolver (`_owner`), above; only `_own_key_line` needed
   own keys, and it has `of_own_key`.
2. (data-steward) Wording of the three new messages. **Answered in
   REFINE:** T names the characters people paste, and says "hidden"
   (see "Message format" under T); T5 names no editor or product, and
   UTF-16 gets its own message (T4b, T5b); G keeps
   `'xyz' is not a valid !!int` — only Dana writes tags, and it reads
   plainly.
3. (tech lead) G: is compose-and-reconstruct worth it for a rare
   mistake, or is `1:1` enough (G1 then drops to should)? The PM's view:
   keep G1 a must, it is cheap and rule 5 names line and column.
   **Settled:** G1 stays a must, at exact positions.
4. (architect) Should `YAMLSource.load`'s catch-all log the original
   exception at debug level, so a genuine ruamel bug is still findable?
   **Settled:** yes, inside the layered catch above.

## Reviewers required

- **qa-engineer** (always): the other ways bytes and YAML node shapes
  reach the loader. Focus: aliases, merges (nested, lists of merges,
  merge of an alias of a merge) and tags in every file the loader reads,
  per iteration 8's lesson.
- **data-steward** (always): wording (Q2); walks T1 and M1 through the
  real CLI.
- **architect** (touches `src/`): Q1, Q4; the single-catch design in
  `YAMLSource`.
- **security-reviewer: not required.** No PROCESS.md trigger: no
  dependency, no secrets, no SQL, no network, no new file location. The
  diagnostics echo a scalar the user wrote into their own terminal, as
  existing diagnostics do.

## Size

**S.** Two methods and one `load` in `config/yamlsource.py`, one call in
`locate`, plus tests. The prototype touched about 80 lines.

## Found in the sweep and not in scope (backlog freeze: not added)

For the owner; none is a traceback.

1. `valid_values: &v [1, *v]` (a list containing itself) warns "item 2
   is empty" instead of saying it is a list.
2. `!!omap` options (`row_count > 0: !!omap [{name: a}]`) load with the
   options silently ignored.
3. `freshness(a) < 99999999999999999d` displays as `100000000000000000d`
   (the number passes through a float).
4. `x-base: &b {…}` as an anchor holder in `tablewatch.yml` is an
   "unknown setting"; docker-compose users will expect it to be allowed.
5. `where: "((((("` passes `validate` and errors at run time (the SQL is
   not parsed at load; fits the existing "validate does not parse SQL"
   behaviour).
6. (data-steward, REFINE) One mistake in an anchored mapping that three
   checks use is three identical diagnostic lines (true today for
   aliases). Collapsing identical `file:line:col` + message lines would
   be kinder; not a traceback, so not here.
