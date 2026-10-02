# Spec 015: check explorer 1, the tree with search and status (I-04 part 1)

- **Track:** light. Frontend only: no `src/`, API, store, identity or exit-code change; `/checks` already serves the data.
- **Size:** S (I-04 is M; split below). **Builder:** ui-engineer. **Reviewers:** qa-engineer, data-steward.
- **Score:** I-04 is R2 × I1 × C0.8 ÷ M2 = 0.8; this half is ÷ S1 = **1.6**. Rank 5 under the owner's "UI first" (2026-09-26), the UI chain's last item, ahead of I-06 (4.5).

## Problem and persona

Sam owns the sales domain. The overview lists every check in one flat table, problems first; with
hundreds of checks he cannot see "my folder" or find the check a colleague named. He scrolls, or
asks Dana to run `tw list checks/sales`. The folder tree is the product's spine (VISION principle 1)
and the UI does not show it yet.

**Split.** Part 1 (this spec): a page at `/checks` with the `checks/` tree, problem counts on every
folder and file, a text search and a status filter, both kept in the URL. Part 2 (stays in I-04):
filters by tag, owner and datasource, held in the URL the same way.

Research: [Soda](https://docs.soda.io/manage-issues/browse-checks) and [Elementary](https://docs.elementary-data.com/cloud/best-practices/governance-for-observability) filter by owner, tag and status; neither shows the source tree.

## Scenarios

Fixture: `recorded` in `frontend/src/test/fixtures/states.ts` (18 checks in `checks/inventory/products.yml`,
`checks/sales/customers.yml`, `checks/sales/orders.yml`: 10 pass, 2 warn, 6 fail). Counts use the
console's words in the overview's order (fail, error, warn, no result, skipped, pass), non-zero only,
joined by ` · `.

| id | | given | expected |
| --- | --- | --- | --- |
| E1 | must | open `/checks` and `/checks/` | the explorer, `<h1>` "Checks"; one `GET /api/v1/checks` and one `/project`; today: "Page not found" |
| E2 | must | `recorded` | root `checks/` reads `18 checks · 6 fail · 2 warn · 10 pass`; under it `inventory/` then `sales/`: folders before files, each sorted by name |
| E3 | must | same | `sales/` reads `14 checks · 6 fail · 1 warn · 7 pass`; `customers.yml` shows its dataset `sales.customers` and `5 checks · 2 fail · 3 pass` |
| E4 | must | same | checks under a file in file order (line, then column); each row: status badge (§5), the name linking to `checkHref(id)`, the expression in monospace when it differs from the name, `display_value` |
| E5 | must | same | a folder or file with a fail, error or warn is open on load; one with only pass, skipped or no result is closed; open/closed is native `<details>`, so it works by keyboard |
| E6 | must | the root is the longest common folder of all `location.file` values | files `checks/a.yml` only: root `checks/`; files in `checks/` and `shared/`: root is unnamed and shows both at the top level; a `..` segment is shown as written |
| E7 | must | type `orders` in the search box | only matching checks stay, with their ancestors; every remaining node is open; counts on nodes are of the **matching** checks; URL becomes `/checks?q=orders` with no new history entry |
| E8 | must | search | case-insensitive substring of name, expression, dataset, file path or id; leading and trailing spaces ignored; `Order VOLUME` finds "Order volume" |
| E9 | must | status filter: one toggle per status present, labelled with its count (`Fail 6`); select Fail and Warn | only fail and warn checks; URL `/checks?status=fail&status=warn`; none selected means all |
| E10 | must | search and status together | both apply (AND); URL `/checks?q=sales&status=fail` |
| E11 | must | open `/checks?q=orders&status=fail`, or click a check then the browser's Back | the page loads with the box filled, Fail selected, the same tree; Back restores it |
| E12 | must | `?status=bogus&status=fail`, `?q=` of 1,000 characters, `?q=<img src=x onerror=alert(1)>` | unknown statuses ignored; `q` cut to 200 characters; text only, never markup, never in an `href` (§9) |
| E13 | must | no check matches | "No checks match." and a link "Clear search and filters" to `/checks` |
| E14 | must | the project has no checks | "No checks are loaded." and no search box |
| E15 | must | `/checks` fails | the section's `LoadError` and Retry, as on the overview; Refresh in the header reloads |
| E16 | must | the overview | a link "Browse all checks" beside "Checks, problems first" goes to `/checks`; the explorer links back to "Overview" |
| E17 | should | the project has check-file errors | the overview's check-file banner (§4.2) shows above the tree: the tree is incomplete |
| E18 | should | 500 checks in 40 folders | first render under 200 ms in vitest/jsdom; typing does not re-fetch |
| E19 | should | under 48rem | the tree stays one column; long file paths wrap rather than scroll the page |
| E20 | must | docs | `docs/UI_SPECIFICATION.md` gains §4B (this page) and the route table; README's UI section names the explorer |

A check's status is `statusOf` (`lib/status.ts`), as on the overview; no new wording for one check.

## Non-goals

- Tag, owner and datasource filters (I-04 part 2).
- A server-side filter or search parameter, pagination, or any API change.
- Sorting other than folder order; a flat "problems first" view (the overview has it).
- `role="tree"` with roving focus; nested lists and `<details>` carry the semantics.
- Remembering open/closed folders across visits (no web storage, §3).

## Open questions (light track: the tech lead answers here before BUILD)

1. **URL updates (tech lead).** Spec 004 decision 7 says "no `pushState`". This spec uses
   `history.replaceState` on each change of `q` or `status` (no new entries), so Back from a check
   restores the view. Accept, or require a submit (`<form method="get">`, a full page load)?
2. **Debounce (tech lead).** Filter on every keystroke, or after 150 ms? E18 decides if needed.
3. **Counts wording (tech lead; the data-steward judges in VERIFY).** `18 checks · 6 fail · 2 warn ·
   10 pass` borrows the console summary (`output/console.py`), reordered problems first. Keep, or
   problems only (`6 fail · 2 warn`)?

## Decisions

1. **Accept `history.replaceState`.** Spec 004 D7 is about moving between pages: no router and no
   `pushState`, and links stay plain `<a href>` with full page loads. Rewriting the current entry's
   query adds no history entry and no navigation, so D7 still holds. A `popstate` handler is not needed.
2. **No debounce.** Filtering runs in memory over a list already loaded. If E18 misses its budget, use
   React's `useDeferredValue`; do not use a timer.
3. **Keep the console wording** (`18 checks · 6 fail · 2 warn · 10 pass`). The total gives the scale
   and the problems come first. The data-steward judges it in VERIFY.
