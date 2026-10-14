/**
 * The app shell and side navigation (spec 039, scenarios N1-N7, S2).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { detailOf } from "./fixtures/detail";
import { interrupted, recorded, type OverviewResponses } from "./fixtures/states";
import { CLOCK, ok, renderOverview, setClock, stubCheckServer, stubServer, UNAVAILABLE, URLS } from "./render";

const EMAIL = "b1ceb8262d8b5441";

beforeEach(() => {
  setClock(CLOCK);
  window.localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
  window.localStorage.clear();
});

async function waitLoaded(): Promise<void> {
  await vi.waitFor(() => {
    if (screen.getByRole("status").textContent === "Loading…") throw new Error("still loading");
  });
}

function nav(): HTMLElement {
  return screen.getByRole("navigation", { name: "Sections" });
}

function navLinks(): HTMLElement[] {
  return within(nav()).getAllByRole("link");
}

/** A fixture with exactly 2 fail, 1 error and 4 pass among its active checks. */
function sevenChecks(): OverviewResponses {
  const base = structuredClone(recorded.checks.items).slice(0, 7);
  const outcomes: ("fail" | "fail" | "error" | "pass" | "pass" | "pass" | "pass")[] = [
    "fail",
    "fail",
    "error",
    "pass",
    "pass",
    "pass",
    "pass",
  ];
  const items = base.map((c, i) => ({
    ...c,
    enabled: true,
    state: "active" as const,
    latest:
      c.latest === null
        ? null
        : {
            ...c.latest,
            outcome: outcomes[i] ?? "pass",
            display_value: outcomes[i] === "error" ? "—" : "0",
            value: outcomes[i] === "error" ? null : 0,
            message: null,
            last_evaluated: null,
          },
  }));
  const next = structuredClone(recorded);
  next.checks = { items, total: items.length };
  next.project.counts.checks = items.length;
  return next;
}

describe("N1: the nav on every page", () => {
  it("lists Dashboard, Checks, Datasets in order, with the current page's link marked", async () => {
    stubServer(recorded);
    render(<App path="/" />);
    await waitLoaded();
    const hrefs = navLinks().map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/checks", "/datasets"]);
    const current = nav().querySelectorAll('a[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe("/");
  });

  it("marks Checks current on the explorer", async () => {
    stubServer(recorded);
    window.history.replaceState(null, "", "/checks");
    render(<App path="/checks" />);
    await waitLoaded();
    const current = nav().querySelectorAll('a[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe("/checks");
  });

  it("marks Checks current on a check's own page", async () => {
    stubCheckServer(EMAIL, { check: ok(detailOf(interrupted, EMAIL)) }, interrupted);
    render(<App path={`/checks/${EMAIL}`} />);
    await waitLoaded();
    const current = nav().querySelectorAll('a[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe("/checks");
  });

  it("marks Datasets current on the datasets page", async () => {
    stubServer(recorded);
    window.history.replaceState(null, "", "/datasets");
    render(<App path="/datasets" />);
    await waitLoaded();
    const current = nav().querySelectorAll('a[aria-current="page"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.getAttribute("href")).toBe("/datasets");
  });

  it("marks no link current on Not found, and makes no request", () => {
    const fetchMock = vi.fn(() => Promise.reject(new Error("no request expected")));
    vi.stubGlobal("fetch", fetchMock);
    render(<App path="/nope" />);
    const hrefs = navLinks().map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/", "/checks", "/datasets"]);
    expect(nav().querySelectorAll('a[aria-current="page"]')).toHaveLength(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("N2: the Checks badge", () => {
  it("shows the count and the accessible name when there are problems", async () => {
    stubServer(sevenChecks(), { problems: ok({ items: [], total: 3 }) });
    render(<App path="/" />);
    await waitLoaded();
    const checksLink = screen.getByRole("link", { name: "Checks, 3 failing or in error" });
    expect(checksLink.textContent).toContain("3");
  });

  it("shows no count when there are no problems", async () => {
    stubServer(recorded, { problems: ok({ items: [], total: 0 }) });
    render(<App path="/" />);
    await waitLoaded();
    expect(screen.queryByRole("link", { name: /failing or in error/ })).toBeNull();
    const checksLink = within(nav()).getByRole("link", { name: "Checks" });
    expect(checksLink.getAttribute("href")).toBe("/checks");
    expect(checksLink.querySelector(".nav-badge")).toBeNull();
  });
});

describe("N3: the badge's request fails or is slow", () => {
  it("fails: no count, and the rest of the page is unaffected", async () => {
    stubServer(recorded, { problems: UNAVAILABLE });
    render(<App path="/" />);
    await waitLoaded();
    expect(screen.queryByRole("link", { name: /failing or in error/ })).toBeNull();
    // The rest of the page still loaded: the summary and the table are there.
    expect(screen.getByRole("region", { name: "Summary" })).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("is slow: no count yet, but the summary and table render from their own slots", async () => {
    let release: (r: Response) => void = () => undefined;
    const slow = new Promise<Response>((r) => {
      release = r;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL): Promise<Response> => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url === URLS.problems) return slow;
      const body =
        url === URLS.project ? recorded.project : url.split("?")[0] === URLS.checks ? recorded.checks : recorded.runs;
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App path="/" />);
    await vi.waitFor(() => {
      expect(screen.getByRole("table")).toBeTruthy();
    });
    expect(screen.queryByRole("link", { name: /failing or in error/ })).toBeNull();
    // A slow badge never holds the page busy: the status settles and Refresh is free.
    await vi.waitFor(() => {
      expect(screen.getByRole("status").textContent).toBe("Up to date.");
    });
    expect(screen.getByRole("button", { name: "Refresh" }).getAttribute("aria-busy")).toBe("false");
    release(new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }));
  });
});

describe("N4: collapsing the nav on a wide screen", () => {
  it("persists the rail across a reload, and every link keeps its accessible name", async () => {
    const first = await renderOverview(recorded);
    const collapse = screen.getByRole("button", { name: "Collapse navigation" });
    expect(collapse.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(collapse);
    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeTruthy();
    expect(window.localStorage.getItem("tablewatch.nav")).toBe("rail");
    for (const name of ["Dashboard", "Checks", "Datasets"]) {
      expect(screen.getByRole("link", { name: new RegExp(`^${name}`) })).toBeTruthy();
    }
    // "Reload": the DOM is torn down and a fresh mount reads the stored preference.
    first.unmount();
    await renderOverview(recorded);
    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeTruthy();
  });
});

describe("N5: storage throws", () => {
  it("stays expanded, and the toggle still works for the page's life", async () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    await renderOverview(recorded);
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeTruthy();
  });
});

describe("N6: an unrecognised stored value", () => {
  it.each(["RAIL", "<img src=x>"])("%s is treated as expanded, and nothing is rendered from it", async (value) => {
    window.localStorage.setItem("tablewatch.nav", value);
    await renderOverview(recorded);
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toBeTruthy();
    expect(document.querySelectorAll("img").length).toBe(0);
    expect(document.body.textContent).not.toContain(value);
  });
});

describe("N7: the narrow-screen drawer", () => {
  async function openDrawer(): Promise<void> {
    await renderOverview(recorded);
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
  }

  it("Escape closes it and returns focus to Menu", async () => {
    await openDrawer();
    expect(document.querySelector(".app-nav--open")).not.toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.querySelector(".app-nav--open")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Menu" }));
  });

  it("the close button closes it and returns focus to Menu", async () => {
    await openDrawer();
    fireEvent.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(document.querySelector(".app-nav--open")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Menu" }));
  });

  it("a click outside (the backdrop) closes it and returns focus to Menu", async () => {
    await openDrawer();
    const backdrop = document.querySelector(".nav-backdrop");
    if (backdrop === null) throw new Error("no backdrop");
    fireEvent.click(backdrop);
    expect(document.querySelector(".app-nav--open")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Menu" }));
  });

  it("opening moves focus into the drawer", async () => {
    await openDrawer();
    expect(document.activeElement?.getAttribute("href")).toBe("/");
  });
});

describe("S2: keyboard order", () => {
  it("skip link, then Menu, then the collapse button is reachable before the page's own links", async () => {
    await renderOverview(recorded);
    const focusable = [...document.querySelectorAll<HTMLElement>("a[href], button")];
    const skipLink = screen.getByRole("link", { name: "Skip to content" });
    const menu = screen.getByRole("button", { name: "Menu" });
    const collapse = screen.getByRole("button", { name: "Collapse navigation" });
    const firstTableLink = within(screen.getByRole("table")).getAllByRole("link")[0];
    if (firstTableLink === undefined) throw new Error("no table link");
    expect(focusable.indexOf(skipLink)).toBe(0);
    expect(focusable.indexOf(menu)).toBeGreaterThan(focusable.indexOf(skipLink));
    expect(focusable.indexOf(collapse)).toBeGreaterThan(focusable.indexOf(menu));
    expect(focusable.indexOf(firstTableLink)).toBeGreaterThan(focusable.indexOf(collapse));
  });
});
