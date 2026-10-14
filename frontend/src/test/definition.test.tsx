/**
 * A check's Definition section and the chart's definition-change marker
 * (spec 038 S8). Every API response is a fixture typed against the
 * generated contract.
 */
import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { detailOf, emailSummary, entry, page } from "./fixtures/detail";
import { clause, definitions, version } from "./fixtures/definitions";
import { interrupted, RUN_ID, STARTED } from "./fixtures/states";
import { CLOCK, checkUrls, notFound, ok, renderCheck, setClock, text, type Answer } from "./render";

const EMAIL = "b1ceb8262d8b5441";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

function section(): HTMLElement {
  return screen.getByRole("region", { name: "Definition" });
}

/** Every version item, open ones first (inside `<details>` or not: both are in the DOM). */
function versionItems(): HTMLElement[] {
  return Array.from(section().querySelectorAll<HTMLElement>(".definition__version"));
}

/** Only the versions shown without opening "N earlier versions". */
function visibleVersionItems(): HTMLElement[] {
  return Array.from(section().querySelectorAll<HTMLElement>(":scope > ul.definition__versions > .definition__version"));
}

function chart(): SVGSVGElement {
  const svg = document.querySelector<SVGSVGElement>("svg.chart__svg");
  if (svg === null) throw new Error("no chart");
  return svg;
}

async function renderEmail(definitionList: Answer, history = page([entry(emailSummary, "A")])): Promise<void> {
  await renderCheck(EMAIL, { check: ok(detailOf(interrupted, EMAIL)), history: ok(history), definitions: definitionList });
}

describe("S6/S8: the empty and loading states", () => {
  it("'No definition recorded yet.' when nothing is recorded", async () => {
    await renderEmail(ok(definitions([])));
    expect(text(section())).toContain("No definition recorded yet.");
  });

  it("a check with recorded history but no row at all reads 'not available', not a failure (P6-style 404)", async () => {
    await renderCheck(EMAIL, {
      check: notFound(),
      history: ok(page([entry(emailSummary, "A")])),
      definitions: notFound(),
    });
    expect(screen.getByRole("status").textContent).toBe("Up to date.");
    expect(text(section())).toContain("not in the loaded check files or the results store");
  });

  it("a non-404 failure shows the load error, with a retry button", async () => {
    await renderEmail({ status: 500, body: { error: { code: "internal_error", message: "internal error" } } });
    expect(screen.getByRole("status").textContent).toBe("Could not load everything.");
    expect(within(section()).getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});

describe("S8: the version list", () => {
  it("the first version shows its clauses, dated, and names its run", async () => {
    const list = definitions([version(1, STARTED.A, RUN_ID.A, [clause("missing_percent(email)", "missing_percent(email) < 5%")])]);
    await renderEmail(ok(list));
    const items = versionItems();
    expect(items).toHaveLength(1);
    expect(text(items[0] ?? section())).toContain("Version 1");
    expect(text(items[0] ?? section())).toContain("missing_percent(email) < 5%");
    expect(text(items[0] ?? section())).toContain(`from run ${RUN_ID.A}`);
  });

  it("a version sync recorded (no run) reads 'recorded by sync'", async () => {
    const list = definitions([version(1, STARTED.A, null, [clause("row_count", "row_count > 0")])]);
    await renderEmail(ok(list));
    expect(text(section())).toContain("recorded by sync");
  });

  it("a changed clause shows old → new in full; an unchanged one is not repeated", async () => {
    const list = definitions([
      version(2, STARTED.B, RUN_ID.B, [clause("missing_percent(email)", "missing_percent(email) < 15%"), clause("row_count", "row_count > 0")]),
      version(1, STARTED.A, RUN_ID.A, [clause("missing_percent(email)", "missing_percent(email) < 5%"), clause("row_count", "row_count > 0")]),
    ]);
    await renderEmail(ok(list));
    const [newest] = versionItems();
    if (newest === undefined) throw new Error("no version item");
    const changed = newest.querySelector('[data-change="changed"]');
    expect(text(changed ?? newest)).toContain("missing_percent(email) < 5% → missing_percent(email) < 15%");
    expect(newest.querySelectorAll("[data-change]")).toHaveLength(1);
    expect(text(newest)).not.toContain("row_count");
  });

  it("added and removed clauses are flagged, each carrying its clause", async () => {
    const list = definitions([
      version(2, STARTED.B, RUN_ID.B, [clause("b", "duplicate_count(id) = 0")]),
      version(1, STARTED.A, RUN_ID.A, [clause("a", "row_count > 0")]),
    ]);
    await renderEmail(ok(list));
    const [newest] = versionItems();
    if (newest === undefined) throw new Error("no version item");
    expect(text(newest.querySelector('[data-change="added"]') ?? newest)).toContain("Added");
    expect(text(newest.querySelector('[data-change="added"]') ?? newest)).toContain("duplicate_count(id) = 0");
    expect(text(newest.querySelector('[data-change="removed"]') ?? newest)).toContain("Removed");
    expect(text(newest.querySelector('[data-change="removed"]') ?? newest)).toContain("row_count > 0");
  });

  it("an option-only change is flagged too, with both options rendered old → new", async () => {
    const list = definitions([
      version(2, STARTED.B, RUN_ID.B, [clause("status", "valid_count(status)", { options: { valid_values: ["a", "b"] } })]),
      version(1, STARTED.A, RUN_ID.A, [clause("status", "valid_count(status)", { options: { valid_values: ["a", "b", "c"] } })]),
    ]);
    await renderEmail(ok(list));
    const [newest] = versionItems();
    if (newest === undefined) throw new Error("no version item");
    const changed = newest.querySelector('[data-change="changed"]');
    expect(text(changed ?? newest)).toContain(
      "valid_count(status); valid_values: [a, b, c] → valid_count(status); valid_values: [a, b]",
    );
  });

  it("reordering clauses with no other change lists no change for that version", async () => {
    const a = clause("a", "row_count > 0");
    const b = clause("b", "missing_count(email) = 0");
    const list = definitions([version(2, STARTED.B, RUN_ID.B, [b, a]), version(1, STARTED.A, RUN_ID.A, [a, b])]);
    await renderEmail(ok(list));
    const [newest] = versionItems();
    if (newest === undefined) throw new Error("no version item");
    expect(newest.querySelectorAll("[data-change]")).toHaveLength(0);
    expect(text(newest)).toContain("No visible clause change.");
  });

  it("keeps the latest few open and the rest behind a disclosure, newest first throughout", async () => {
    const list = definitions(
      [5, 4, 3, 2, 1].map((n) =>
        version(n, STARTED.A, RUN_ID.A, [clause("a", `missing_count(email) = ${String(5 - n)}`)]),
      ),
    );
    await renderEmail(ok(list));
    expect(visibleVersionItems().map((i) => i.dataset.version)).toEqual(["5", "4", "3"]);
    const summary = within(section()).getByText("2 earlier versions");
    expect(section().querySelector("details")?.hasAttribute("open")).toBe(false);
    summary.closest("details")?.setAttribute("open", "");
    expect(versionItems().map((i) => i.dataset.version)).toEqual(["5", "4", "3", "2", "1"]);
  });
});

describe("S8: the history chart marks a definition change", () => {
  it("draws a dashed marker labelled 'definition v2', with a caption naming the runs and the version", async () => {
    const hist = page([
      entry(emailSummary, "B", { value: 20, display_value: "20.00%", definition_version: 2 }),
      entry(emailSummary, "A", { value: 20, display_value: "20.00%", definition_version: 1 }),
    ]);
    await renderEmail(ok(definitions([])), hist);
    const marker = chart().querySelector(".chart__marker--definition");
    expect(marker).not.toBeNull();
    expect(text(marker as Element)).toBe("definition v2");
    const caption = document.querySelector("[data-definition-change]");
    expect(text(caption ?? document.body)).toContain("to version 2");
  });

  it("no marker when every result predates definitions (all null)", async () => {
    const hist = page([
      entry(emailSummary, "B", { value: 20, display_value: "20.00%" }),
      entry(emailSummary, "A", { value: 20, display_value: "20.00%" }),
    ]);
    await renderEmail(ok(definitions([])), hist);
    expect(chart().querySelectorAll(".chart__marker--definition")).toHaveLength(0);
  });
});

describe("S8: a retired or not-loaded check still answers", () => {
  it("requests /definitions alongside the other endpoints, with the id encoded", async () => {
    const urls = checkUrls(EMAIL);
    await renderEmail(ok(definitions([])));
    expect(urls.definitions).toBe(`/api/v1/checks/${EMAIL}/definitions`);
    expect(screen.getByRole("region", { name: "Definition" })).toBeTruthy();
  });
});
