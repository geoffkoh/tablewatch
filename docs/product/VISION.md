# Vision

## The problem

Bad data is found by the people who use it — an analyst whose dashboard
looks wrong, a regulator's report that doesn't reconcile — long after it
arrived. Teams that want to catch it earlier face a poor choice: write ad-hoc
SQL checks nobody maintains, adopt an open-source tool whose enterprise
features (single sign-on, access control, audit, alerting at scale) sit
behind a paid tier, or buy a SaaS product that must be given access to
production data.

## What tablewatch is

A data quality tool that teams run themselves, where the checks live in git
as plain YAML and run inside the database:

- **Checks as code.** YAML files in folders that mirror how the organisation
  thinks about its data, reviewed in pull requests like any other code.
- **Cheap to run.** Every aggregate check on a table is answered by one scan.
- **Honest outcomes.** `fail` means the data is bad; `error` means tablewatch
  couldn't tell. They go to different people.
- **Precise feedback.** Every mistake in a check file is reported at its
  `file:line:col`.
- **Enterprise-ready without a paywall.** Governance — SSO, access control,
  audit, governed changes to checks — is part of the open product.

## Personas

| Persona | Who | Needs |
| --- | --- | --- |
| **Dana** — data engineer | Writes checks; runs them in pipelines and CI | Fast feedback, precise errors, low query cost, works in CI |
| **Sam** — data steward / domain owner | Owns a domain's data quality; may not write SQL | See status, get alerted, understand failures, sign off |
| **Priya** — platform / SRE | Deploys and operates tablewatch | HA, observability, least privilege, predictable DB load |
| **Alex** — data consumer / analytics lead | Uses data to make decisions | A trust signal before using a dataset; health and SLAs |
| **Ravi** — risk / compliance / audit | Needs evidence of controls, e.g. BCBS 239 in banking | Audit trail, sign-off, retention, evidence packs |

## Product principles

1. **The folder tree is the product's spine.** It organises, selects,
   inherits, navigates the UI, and (later) scopes permissions.
2. **Never cry wolf.** Alert on state changes, not on every run. A tool that
   pages people for known problems gets switched off.
3. **Every number is explainable.** A user can see the SQL behind any value
   (`tablewatch compile`) and the reason behind any outcome.
4. **Safe by default.** No row data is stored unless asked for; secrets are
   references; tablewatch needs only read access. Caching and incremental
   runs keep **numbers, never rows**: tablewatch does not extract or cache
   table data on disk (owner, 2026-10-04). The one opt-in exception is
   failed-row samples (B6), off by default, masked, and stored in the results
   store with retention.
5. **Small, vertical, shippable.** Each increment is usable end to end.
6. **Same meaning everywhere.** A check gives the same answer on every
   database it supports.

## North-star measures

Until there are real users, these are measured against the example project
and the test suite:

| Measure | Target |
| --- | --- |
| Time from `pip install` to a first passing check | < 5 minutes |
| Queries per dataset per run | 1 scan + only what cannot be aggregated |
| Diagnostics located at `file:line:col` | 100% |
| Alerts per unchanged failure | 1 (on the change), then silence |
| Planted defects in `examples/retail` caught | all, with no false positives |
| Metrics giving identical results on every tested database | 100% |

## Positioning against alternatives

| Alternative | Where tablewatch differs |
| --- | --- |
| Soda Core | Similar YAML approach; tablewatch puts governance and UI in the open product |
| Great Expectations | Configuration in YAML rather than Python suites; one scan per table |
| dbt tests | Not tied to dbt models; runs on any table, keeps history and alerts |
| Monte Carlo and SaaS observability | Self-hosted; no production data leaves your network |
| Hand-written SQL checks | History, alerting, ownership, and precise feedback included |
