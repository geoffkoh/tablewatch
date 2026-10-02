# Spec 016: check explorer 2, filters by tag, owner and datasource (I-04 part 2)

- **Track:** light. Frontend only: `/api/v1/checks` already serves `tags`, `owner`, `datasource` and `datasource_state` per check (`server/schemas.py` `CheckSummary`); no `src/`, API, store, identity or exit-code change.
- **Size:** S (I-04 is M; this is its second and last half). **Builder:** ui-engineer. **Reviewers:** qa-engineer, data-steward.
- **Score:** I-04 is R2 × I1 × C0.8 ÷ M2 = 0.8; this half is ÷ S1 = **1.6**. Rank 5, the UI chain's last item ("UI first", 2026-09-26). I-21 (0.8) is not batched: it is a different page with its own wording calls; it is the candidate for iteration 17.

## Problem and persona

Sam owns the sales domain; Priya owns the platform's datasets. Spec 015 gave them the `checks/` tree, a
search and a status filter, but owners and tags often cut across folders ("everything `tier-1`", "what
`sales-data@` owns"), and a project with a staging and a production copy cannot be split by datasource. Today
they search for a folder name and hope it matches, or ask Dana to run `tw run --tag tier-1`.
Research: [Soda](https://docs.soda.io/manage-issues/browse-checks) and [Elementary](https://docs.elementary-data.com/cloud/best-practices/governance-for-observability) both filter checks by owner and tag; values within a filter combine with OR, filters with AND.

## Scenarios

Fixture `recorded` (`frontend/src/test/fixtures/states.ts`): `inventory/products.yml` (4 checks, owner
`data-platform@example.com`, tags `example`, `catalogue`); `sales/customers.yml` (5) and `sales/orders.yml`
(9), owner `sales-data@example.com`, tags `example`, `sales`, `tier-1`; every check on datasource `lake`.
Filters are `<fieldset>`s after Status, in the order Status, Tag, Owner, Datasource, built like Status
(§4B.3): one checkbox per value, labelled with the value and a count. "Ticked" below means checked.

| id | | given | expected |
| --- | --- | --- | --- |
| F1 | must | `recorded`, open `/checks` | fieldset "Tag": `catalogue 4`, `example 18`, `sales 14`, `tier-1 14`; "Owner": `data-platform@example.com 4`, `sales-data@example.com 14`; no "Datasource" fieldset (one value, nothing to choose) |
| F2 | must | values in a fieldset | sorted by name, case-insensitive; the "none" value (F7) last; values are text, never markup or an `href` (§9) |
| F3 | must | tick tag `catalogue` | only `inventory/products.yml`'s 4 checks; URL `/checks?tag=catalogue` via `replaceState` |
| F4 | must | tick tags `catalogue` and `tier-1` | 18 checks: values in one filter combine with OR, as `tw run --tag a --tag b` (`selection.py`: any tag matches) |
| F5 | must | tick status Fail and owner `sales-data@example.com` | 6 checks (filters combine with AND, with each other and with the search); URL `/checks?status=fail&owner=sales-data%40example.com` |
| F6 | must | counts with status Fail ticked | each count is of the checks that match the search and every **other** filter: Owner reads `data-platform@example.com 0`, `sales-data@example.com 6`; a value with 0 stays listed; Status counts now also follow the tag, owner and datasource filters |
| F7 | must | checks with `owner: null` beside owned ones; a dataset with no tags | Owner gains "No owner" (URL `owner=` with an empty value); Tag gains "No tags" (`tag=`); each is shown only when some check has it |
| F8 | must | derived fixture: `orders.yml` on `warehouse` (`defined`), `customers.yml` on `staging` (`not_defined`), `products.yml` with `datasource_state` `none` (`datasource` `""`) | "Datasource": `staging (not defined) 5`, `warehouse 9`, `No datasource 4`; the URL holds the name as written (`datasource=staging`), `datasource=` for "No datasource" |
| F9 | must | a filter with one value and nothing ticked | the fieldset is not shown (F1); it is shown, ticked, when the URL selects a value |
| F10 | must | open `/checks?q=orders&status=fail&tag=tier-1&owner=sales-data%40example.com` | the box filled, each box ticked, the same tree; URL parameters in the order `q`, `status`, `tag`, `owner`, `datasource`; Back from a check restores it (as E11) |
| F11 | must | `?tag=removed` (a value no loaded check has) | a ticked `removed 0` checkbox the user can untick; "No checks match." with "Clear search and filters" |
| F12 | must | `?tag=` with 1,000 characters, `?owner=<img src=x onerror=alert(1)>`, the same value twice | each value cut to 200 code points (as `q`); text only; duplicates kept once |
| F13 | must | search `tier-1`, `sales-data`, or `lake` | the search also matches a check's tags, owner and datasource (spec 015 E8 left them out); substring, case-insensitive |
| F14 | must | "Clear search and filters" (E13) and the "Showing *n* of *N* checks." line | clear every filter, not only `q` and status; the line counts all filters |
| F15 | should | 60 distinct tags | the Tag fieldset shows the first 10 by count and a "Show all 60" button; ticked values always show |
| F16 | should | 500 checks, 40 tags, 20 owners | E18's budget still holds (first render under 200 ms in vitest/jsdom, best of 3) |
| F17 | must | docs | `docs/UI_SPECIFICATION.md` §4B.3 gains the three filters and drops "part 2" notes (lines ~939, ~1281); README's UI section names them |

A check's tags are its dataset's (`CheckSummary.tags`; checks have none of their own).

## Non-goals

- Server-side filtering or new query parameters on `/api/v1/checks`; any API change.
- Filters by severity, metric or dataset (the search covers dataset); saved views.
- An "all of these tags" (AND) mode within one filter.
- Changing the overview page (I-21) or the check page.

## Open questions (light track: the tech lead answers here before BUILD)

1. **"None" in the URL (tech lead).** `owner=` / `tag=` / `datasource=` with an empty value for "No owner",
   "No tags", "No datasource" (F7, F8). Accept, or a reserved word (which a real owner could collide with)?
2. **Unknown URL values (tech lead).** F11 keeps them ticked at 0 so a stale shared link explains itself;
   status (spec 015 E12) ignores unknown values. Accept the difference (status has a closed set, these do not)?
3. **Hiding one-value filters (tech lead; the data-steward judges in VERIFY).** F1/F9 hide a filter with a
   single value. Keep, or always show all four filters for a stable layout?

## Decisions


1. **Accept the empty value** (`owner=`, `tag=`, `datasource=`). A reserved word could collide with a real
   value; no real owner, tag or datasource name is `""`.
2. **Accept: unknown values stay ticked at 0.** Status has a closed set; these do not, and a stale link
   should explain itself.
3. **Keep hiding a one-value filter** (F1, F9); the data-steward judges it in VERIFY.
4. **`not_a_name` goes under "No datasource".** It is served as `datasource: ""`, like `none`, so both
   share `datasource=`; the check page says which (spec 014).
5. **VERIFY (qa-engineer, blocking):** cutting the data's own values to 200 code points made a longer
   real value match nothing. Now only URL input is cut, to 1,000 code points (F12 amended), and a blank
   tag in the data (`tags: [sales, ""]`) counts as no tag.
