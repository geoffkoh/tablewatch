/** Spec 004 decision 7: the route table, and every link and API path encoded. */
import { describe, expect, it } from "vitest";
import { checkHref, parseRoute } from "../lib/route";

describe("parseRoute", () => {
  it.each([
    ["/", { page: "overview" }],
    ["/index.html", { page: "overview" }],
    ["/checks", { page: "explorer" }],
    ["/checks/", { page: "explorer" }],
    ["/checks/b1ceb8262d8b5441", { page: "check", id: "b1ceb8262d8b5441" }],
    ["/checks/b1ceb8262d8b5441/", { page: "check", id: "b1ceb8262d8b5441" }],
    ["/checks/customer-email-completeness", { page: "check", id: "customer-email-completeness" }],
    ["/checks/sales.orders:volume_1", { page: "check", id: "sales.orders:volume_1" }],
    ["/checks/a%2Db", { page: "check", id: "a-b" }],
    [`/checks/${"a".repeat(64)}`, { page: "check", id: "a".repeat(64) }],
  ])("%s is %j", (path, route) => {
    expect(parseRoute(path)).toEqual(route);
  });

  it.each([
    "/checks//",
    "/checks.html",
    "/checks/?q=x",
    "/checks/a/b",
    "/checks/..",
    "/checks/%2e%2e",
    "/checks/a%2Fb",
    "/checks/a%3Fb",
    "/checks/%",
    "/checks/%E0%A4%A",
    "/checks/.hidden",
    "/checks/-x",
    "/checks/a%20b",
    `/checks/${"a".repeat(65)}`,
    "/runs/abc",
    "/check/abc",
    "/checks/abc/history",
  ])("%s is page not found", (path) => {
    expect(parseRoute(path)).toEqual({ page: "not-found" });
  });
});

describe("checkHref", () => {
  it("encodes the id", () => {
    expect(checkHref("b1ceb8262d8b5441")).toBe("/checks/b1ceb8262d8b5441");
    expect(checkHref("customer-email-completeness")).toBe("/checks/customer-email-completeness");
    expect(checkHref("a:b")).toBe("/checks/a%3Ab");
    expect(checkHref("a/b?c#d")).toBe("/checks/a%2Fb%3Fc%23d");
  });

  it("round-trips through parseRoute for every valid id", () => {
    for (const id of ["b1ceb8262d8b5441", "a:b", "x.y_z-1"]) {
      expect(parseRoute(checkHref(id))).toEqual({ page: "check", id });
    }
  });
});
