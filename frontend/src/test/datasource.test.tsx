/**
 * Spec 014: the check page's Datasource row names an undefined datasource as
 * written (U6), marks a missing one as a gap (U7), never echoes a value that
 * is not a name (U10), and leaves a defined one as it was (U9).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckDetail, CheckSql } from "../api/types";
import { detailOf, recordedHistory } from "./fixtures/detail";
import { recorded } from "./fixtures/states";
import { CLOCK, ok, renderCheck, setClock, text } from "./render";

beforeEach(() => {
  setClock(CLOCK);
});

afterEach(() => {
  vi.useRealTimers();
});

const EMAIL = "b1ceb8262d8b5441";

function withDatasource(datasource: string, state: CheckDetail["datasource_state"]): CheckDetail {
  return { ...detailOf(recorded, EMAIL), datasource, datasource_state: state };
}

function cannotCompile(datasource: string, error: string): CheckSql {
  return {
    check_id: EMAIL,
    dataset: "sales.customers",
    datasource,
    dialect: null,
    statements: [],
    schema_lookup: false,
    error,
  };
}

async function renderWith(check: CheckDetail, sql?: CheckSql): Promise<void> {
  await renderCheck(EMAIL, {
    check: ok(check),
    history: ok(recordedHistory(EMAIL)),
    ...(sql === undefined ? {} : { sql: ok(sql) }),
  });
}

/** The `<dd>` of the identity row labelled `label`. */
function fact(label: string): HTMLElement {
  const dt = Array.from(document.querySelectorAll(".check-identity dt")).find((d) => d.textContent === label);
  const dd = dt?.parentElement?.querySelector("dd");
  if (!(dd instanceof HTMLElement)) throw new Error(`no ${label} row`);
  return dd;
}

const NOT_DEFINED_ERROR = "datasource 'warehous' is not defined in tablewatch.yml; run tablewatch validate";
const NONE_ERROR =
  "this dataset has no datasource; add datasource: to its check file or a _defaults.yml; run tablewatch validate";
const NOT_A_NAME_ERROR =
  "this dataset's datasource: value is not a name defined in tablewatch.yml; run tablewatch validate";

describe("U6: a datasource that is not defined is shown by name", () => {
  it("reads 'warehous (not defined)', the marker quiet and the name not", async () => {
    await renderWith(withDatasource("warehous", "not_defined"), cannotCompile("warehous", NOT_DEFINED_ERROR));
    const dd = fact("Datasource");
    expect(text(dd)).toBe("warehous (not defined)");
    const quiet = dd.querySelectorAll(".quiet");
    expect(quiet).toHaveLength(1);
    expect(quiet[0]?.textContent).toBe("(not defined)");
  });

  it("shows the server's reason under 'Cannot compile'", async () => {
    await renderWith(withDatasource("warehous", "not_defined"), cannotCompile("warehous", NOT_DEFINED_ERROR));
    const sql = document.getElementById("sql-heading")?.closest("section") ?? null;
    if (sql === null) throw new Error("no SQL section");
    expect(text(sql)).toContain("Cannot compile");
    expect(text(sql)).toContain(NOT_DEFINED_ERROR);
  });

  it("marks invisible characters in the written name", async () => {
    await renderWith(withDatasource("ware​hous", "not_defined"));
    expect(fact("Datasource").querySelector(".invisible-char")).not.toBeNull();
  });
});

describe("U7: no datasource set reads as a gap", () => {
  it("reads 'none set', styled like Owner's 'none'", async () => {
    await renderWith({ ...withDatasource("", "none"), owner: null }, cannotCompile("", NONE_ERROR));
    const dd = fact("Datasource");
    expect(text(dd)).toBe("none set");
    expect(dd.querySelector(".quiet")?.textContent).toBe("none set");
    expect(fact("Owner").querySelector(".quiet")?.className).toBe(dd.querySelector(".quiet")?.className);
  });
});

describe("U10: a value that is not a name is never shown", () => {
  it("reads 'not a datasource name'", async () => {
    await renderWith(withDatasource("", "not_a_name"), cannotCompile("", NOT_A_NAME_ERROR));
    const dd = fact("Datasource");
    expect(text(dd)).toBe("not a datasource name");
    expect(dd.querySelector(".quiet")?.textContent).toBe("not a datasource name");
  });

  it("ignores any name the server sends alongside not_a_name", async () => {
    await renderWith(withDatasource("postgresql://admin:Pa55w0rd@db.prod/x", "not_a_name"));
    expect(text(fact("Datasource"))).toBe("not a datasource name");
  });
});

describe("U9: a defined datasource is unchanged", () => {
  it("reads the bare name with no marker", async () => {
    await renderWith(withDatasource("lake", "defined"));
    const dd = fact("Datasource");
    expect(text(dd)).toBe("lake");
    expect(dd.querySelector(".quiet")).toBeNull();
  });
});
