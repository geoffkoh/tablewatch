# Iteration log

One entry per iteration, newest first. Written by the product-manager in the
REVIEW step; proposals needing the user's decision are also recorded here.

Each entry records: the spec, the PR, acceptance results, reviewer findings
and how they were resolved, what was deferred, and what was learned.

## Before the loop

- **Phase 1** shipped as PR #1: engine, check language, CLI, results store —
  `0.1.0`. Built before the loop existed; see `CHANGELOG.md`.
- The product team and this process were set up in PR #2. A read-only
  smoke test of the product-manager found seven inconsistencies in these
  documents (nothing could become "ready"; the log and CHANGELOG were due
  after the merge that required them; five Phase 2 features were missing from
  the roadmap; an ambiguous security trigger), all fixed in the same PR.
