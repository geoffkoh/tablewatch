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
| `product-manager` | judge / planner | `docs/product/**`, `CHANGELOG.md` |
| `data-steward` | judge / domain expert | `examples/**`, fixtures, user docs |
| `qa-engineer` | judge | `tests/**` |
| `security-reviewer` | judge, read-only | nothing |
| `ui-engineer` | builder | `frontend/**`, `docs/UI_SPECIFICATION.md`, static bundle |
| `platform-engineer` | builder | `src/tablewatch/datasources/**`, extras, `deploy/**`, `benchmarks/**` |

Builders never judge their own work.

## One iteration

One iteration is one **PR-sized vertical slice**: usable end to end,
reviewable in one sitting.

| Step | Who | Does | Produces |
| --- | --- | --- | --- |
| 1 PLAN | product-manager | Picks the top-scoring `proposed` or `ready` item whose dependencies are met, and writes its spec — which makes it ready | `docs/product/specs/NNN-slug.md` |
| 2 REFINE | data-steward (+ ui-engineer for UI) | Adds concrete acceptance scenarios; finds semantic traps; the PM settles disagreements | Updated spec |
| 3 BUILD | tech lead, ui-engineer, platform-engineer | Implements on branch `iter/NNN-slug`; acceptance scenarios become tests first | Commits |
| 4 VERIFY | tech lead, qa-engineer, security-reviewer (if flagged), data-steward | Gates and the example; adversarial review; security review; acceptance | Verdicts; blocking findings fixed |
| 5 REVIEW | product-manager | On the iteration branch, before merge: logs the iteration, writes the CHANGELOG entry, re-ranks, names the next item | `ITERATIONS.md`, `CHANGELOG.md`, `BACKLOG.md` |
| 6 SHIP | tech lead | PR linking the spec with evidence; merges under the policy below | Merged PR |

REVIEW comes **before** SHIP so that each PR carries its own log entry,
CHANGELOG and backlog update, and merging is the last act of the iteration.

Each iteration starts from an up-to-date `main`. Branches are never stacked.

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

A spec is ready when it has: a persona and a problem; Given/When/Then
acceptance scenarios with real YAML, each marked `must` or `should`;
non-goals; met dependencies; a size; and its required reviewers.

**security-reviewer is required** when the change adds a dependency or
touches secrets or credentials, authentication or authorisation, how
user-written SQL is executed or what can reach SQL, network calls (inbound
or outbound), writing files to a new place, or storing or exposing row data.
Writing to the existing results store or to a user-named `--output-file` does
not by itself trigger a review. qa-engineer and data-steward are always
required.

## Definition of done

- Every `must` scenario passes as an automated test.
- `pytest`, `ruff check`, `ruff format --check`, strict `mypy` pass; for UI
  work also `tsc` and `vite build`.
- No open **blocking** finding from any required reviewer.
- User docs updated **where the change affects them** (`docs/check-language.md`,
  README, `docs/ROADMAP.md`).
- The REVIEW step is done on the branch: `ITERATIONS.md` entry, `CHANGELOG.md`
  entry under `Unreleased`, backlog updated.
- The PR is open and CI is green.

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
