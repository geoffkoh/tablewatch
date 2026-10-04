# How tablewatch is built: the iteration loop

Every change to tablewatch after Phase 1 goes through this loop. It is
written for the agents in `.claude/agents/` as much as for people; each
step names who does it.

## The team

The **main session is the tech lead**: it runs every step, builds core
Python (engine, CLI, API), integrates, runs the gates, opens and merges PRs.
Subagents cannot start other subagents, so all hand-offs go through the tech
lead and through files.

| Agent | Kind | Writes |
| --- | --- | --- |
| `product-manager` | planner (PLAN only) | `docs/product/**` |
| `data-steward` | judge / domain expert | `examples/**`, fixtures, user docs |
| `qa-engineer` | judge | `tests/**` |
| `security-reviewer` | judge, read-only | nothing |
| `architect` | judge, read-only | nothing |
| `ui-engineer` | builder | `frontend/**`, `docs/UI_SPECIFICATION.md`, static bundle |
| `platform-engineer` | builder | `src/tablewatch/datasources/**`, extras, `deploy/**`, `benchmarks/**` |

Builders never judge their own work.

## One iteration

One iteration is one **PR-sized vertical slice**: usable end to end,
reviewable in one sitting. Small items with the same reviewers may be
**batched** into one iteration (one spec, one PR) as long as the batch stays
S: the cost of an iteration is mostly fixed, so three wording fixes should
not pay it three times.

### Two tracks

Pick the track in PLAN; the spec states it.

**Full track** — when the change touches any **risk trigger**: security
(the security-reviewer triggers below), a public API or wire contract, check
identity, stored data or results semantics, the exit-code contract, a new
dependency, or a new seam.

| Step | Who | Does | Produces |
| --- | --- | --- | --- |
| 1 PLAN | product-manager | Picks the item(s); writes the spec (≤ 150 lines) | `docs/product/specs/NNN-slug.md` |
| 2 REFINE | only the reviewers the spec's open questions name (architect for a seam/API, security for a trigger, data-steward for semantics, ui-engineer for UI) — run in parallel | Answer the open questions; the data-steward may edit the spec, others report | Answers |
|  | tech lead | Records the decisions in the spec's "Decisions" section (no separate settle session); resolves disagreements, security wins on security | Ready spec |
| 3 BUILD | tech lead, ui-engineer, platform-engineer | Scenarios become tests first | Commits |
| 4 VERIFY | qa-engineer, data-steward, plus architect/security **only if they did not review in REFINE**; if they did, a **targeted re-check** when the build departs from REFINE (below) | Adversarial review, acceptance, design/security check | Verdicts; blocking findings fixed |
| 5 REVIEW | tech lead (no PM session) | Log entry, CHANGELOG, backlog status, next item | Docs on the branch |
| 6 SHIP | tech lead | PR, merge under the policy below | Merged PR |

**Light track** — everything else: wording, UI polish, small fixes, docs,
hardening that changes no contract.

| Step | Who | Does |
| --- | --- | --- |
| 1 PLAN | product-manager | Spec ≤ 80 lines: problem, scenarios table, non-goals |
| 2 BUILD | builder | Scenarios become tests |
| 3 VERIFY | qa-engineer + **one** domain reviewer (data-steward for language/messages, ui-engineer's work judged by the data-steward for UI) | Verdicts; blocking findings fixed |
| 4 REVIEW + SHIP | tech lead writes the ITERATIONS entry, CHANGELOG line and backlog status itself; PR; merge | Merged PR |

No REFINE on the light track: open questions are answered by the tech lead
in the spec, or the item moves to the full track.

REVIEW comes **before** SHIP so that each PR carries its own log entry,
CHANGELOG and backlog update, and merging is the last act of the iteration.

Each iteration starts from an up-to-date `main`. Branches are never stacked.

### Keeping the loop cheap

These rules exist because a cold-started agent re-reads its brief, the spec
and the code every time; the cost is per session, not per line changed.

- **Specs are short.** Full track ≤ 150 lines, light ≤ 80. Scenarios are a
  table (given → expected, exact strings) rather than prose. No "today we
  measured" narrative beyond one line per scenario; no restated rationale;
  research is one line with links.
- **One review per role per iteration.** A reviewer who settled the design
  in REFINE does not review the build again. If the build departs from
  REFINE, or the tech lead wants a second look at a risky part, it is a
  **targeted re-check**: the reviewer gets the diff of the named functions and
  the requirements to confirm (e.g. "R1–R8 against `store.py:resolve_url_env`"),
  not the spec and the whole branch. The tech lead says in the iteration entry
  when a re-check ran and why.
- **Reports are ≤ 15 lines:** verdict, blocking findings, non-blocking
  findings (each one line, with file:line), files changed. No list of what
  holds. Every brief says so.
- **Briefs point at files and functions.** Hand-offs go through files (the
  spec's Decisions section, a short notes file), not long pasted prompts. A
  VERIFY brief names the commit, the changed files and functions, and the
  scenarios to cover, so the reviewer does not explore the repository.
- **Agents do not re-read what they already have.** `CLAUDE.md` is loaded
  into every session; reading it again is waste. Each agent reads only its
  own list, and only the part of a long file it needs.
- **Acceptance is bounded.** The data-steward runs the spec's `must`
  scenarios through the CLI, in one scratch project, and stops: no open-ended
  exploration. Anything beyond the scenarios is one line in the report.
- **A fresh session per iteration — enforced.** The tech lead's own
  context is the largest cost of the loop: a session that carries earlier
  iterations re-sends them on every turn. One iteration per session (or
  `/compact` between iterations); all state is in `ITERATIONS.md`,
  `BACKLOG.md`, the specs and memory.
- **Hand browser checks** (several engines, sizes, schemes) only when the
  change alters copy, selection, layout or rendering; otherwise vitest.
- **Gates run once per step**, one pytest process at a time (two concurrent
  runs deadlock on the example's DuckDB file). Agents use targeted test
  files; the tech lead runs the full suite before commit and before the PR.
- **Model per role** (set in each agent's frontmatter). Opus for
  qa-engineer, security-reviewer and architect, whose findings carry the
  merge decision. Sonnet for the product-manager (PLAN), the data-steward,
  the platform-engineer and the ui-engineer; `effort: medium` for the
  product-manager and platform-engineer.
- **Files stay short.** `BACKLOG.md` holds the open items and a short
  header; done items and the running log live in `docs/product/archive/`.
  `ITERATIONS.md` holds the latest entries; older ones are archived there
  too. Agents never read the archive unless a brief points at it.
- **Stalls.** A stalled agent is resumed once with "continue from the files
  you wrote"; a second stall means the tech lead finishes that step itself.

## Scoring (RICE)

`score = reach × impact × confidence ÷ effort`, then modifiers:

| Factor | Scale |
| --- | --- |
| Reach | Personas materially helped, 1–5 |
| Impact | 0.5 low · 1 medium · 2 high · 3 massive |
| Confidence | 0.5 guess · 0.8 some evidence · 1.0 strong evidence |
| Effort | S = 1 · M = 2 · L = 4 (iterations) |
| Unblocking bonus | × 1.25 if other items depend on it |
| Roadmap fit | Finish the current phase first; exceptions are argued in writing |

## Definition of ready

A spec is ready when it has: its track; a persona and a problem; acceptance
scenarios (a table of given → expected, with real YAML where it matters),
each marked `must` or `should`; non-goals; met dependencies; a size; its
required reviewers; and, on the full track, a Decisions section once REFINE
is done. It stays within the length cap above.

**security-reviewer is required** when the change adds a dependency or
touches secrets or credentials, authentication or authorisation, how
user-written SQL is executed or what can reach SQL, network calls (inbound
or outbound), writing files to a new place, or storing or exposing row data.
Writing to the existing results store or to a user-named `--output-file` does
not by itself trigger a review. qa-engineer is always required; the
data-steward on the full track, or as the light track's one domain reviewer.

**architect is required** on the full track when the change touches `src/`.
It reviews design against the rules in `CLAUDE.md`, the module boundaries
and the extension seams; the tech lead builds the core, so it must not judge
that design itself. It reviews **once**: in REFINE when a spec adds a seam
or public API, otherwise in VERIFY. A light-track change to `src/` that adds
no seam and changes no contract does not need it.

## Definition of done

- Every `must` scenario passes as an automated test.
- `pytest`, `ruff check`, `ruff format --check`, strict `mypy` pass; for UI
  work also `tsc` and `vite build`.
- No open **blocking** finding from any required reviewer.
- User docs updated **where the change affects them** (`docs/check-language.md`,
  README, `docs/ROADMAP.md`).
- The REVIEW step (the tech lead's) is done on the branch: `ITERATIONS.md` entry (≤ 30
  lines), `CHANGELOG.md` entry under `Unreleased`, backlog updated.
- The PR is open and CI is green.

A failing supply-chain step in CI (`npm audit`, `npm audit signatures`) is
fixed by upgrading the dependency, or by a time-boxed exception written
down in the PR and in `ITERATIONS.md` with the advisory, the reason and an
expiry date. It is never fixed by removing or weakening the step.

## Merge policy — auto-merge when green

Granted by the user on 2026-09-26, **for tablewatch only**.

The tech lead merges an iteration PR with
`gh pr merge <n> --merge --delete-branch` only when **all** hold:

1. CI is green on the PR;
2. every required reviewer has reported, with no open blocking finding;
3. the definition of done is met.

Every merge goes through a numbered PR. After merging, the tech lead pulls
`main` and continues. The user reviews after the fact through
`ITERATIONS.md` and the PR history.

`gh` is at `/opt/miniconda3/envs/tablewatch/bin/gh` (not on PATH; already
authenticated).

## Product manager autonomy

The PM may re-rank, split, combine, and add items that fit the roadmap's
phases (1, 2, 2b, 3, 4, 5). A new theme, skipping ahead a phase, or changing the roadmap is
written as a proposal in `ITERATIONS.md`, and the loop stops for the user.

## The loop stops and asks the user when

- anything is outward-facing: a PyPI release, a new external service, a
  licence or trademark question;
- a PR cannot meet the merge conditions — CI keeps failing, or a blocking
  finding can't be resolved;
- a change would break a design rule in `CLAUDE.md` or the exit-code
  contract;
- the PM proposes something outside its autonomy;
- the agreed number of iterations is done.

**The iteration count is the brake.** "Run 3 iterations" runs three. With no
number, the tech lead runs one iteration and stops.

**The backlog freeze** (owner, 2026-09-28) holds until the owner lifts it:
no new backlog items; a review follow-up is folded into an existing item or
listed in the iteration entry under "Not added (backlog freeze)".
