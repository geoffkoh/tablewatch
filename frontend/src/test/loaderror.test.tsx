/**
 * `LoadError` as a building block (spec 005, P7): unique heading ids, a
 * heading level for failures nested in a section, and section-scoped wording.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ApiFailure } from "../api/api";
import { LoadError } from "../components/LoadError";

const FAILURE: ApiFailure = { kind: "http", status: 500, code: "internal_error", message: "boom" };
const noop = (): void => undefined;

describe("LoadError", () => {
  it("defaults to an h2 with the page-scoped wording", () => {
    render(<LoadError what="the project" failure={FAILURE} onRetry={noop} />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByRole("heading", { level: 2 }).textContent).toBe("Could not load the project");
    expect(alert.textContent).toContain("Nothing below is shown until it loads");
  });

  it("names its alert by its own heading, and two on one page never share an id", () => {
    render(
      <>
        <LoadError what="the history" failure={FAILURE} onRetry={noop} />
        <LoadError what="older results" failure={FAILURE} onRetry={noop} />
      </>,
    );
    const alerts = screen.getAllByRole("alert");
    const ids = alerts.map((a) => a.getAttribute("aria-labelledby"));
    expect(new Set(ids).size).toBe(2);
    expect(screen.getByRole("alert", { name: "Could not load the history" })).toBeTruthy();
    expect(screen.getByRole("alert", { name: "Could not load older results" })).toBeTruthy();
  });

  it("takes a heading level and section-scoped wording", () => {
    render(<LoadError what="the SQL" failure={FAILURE} onRetry={noop} level={3} scope="section" />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByRole("heading", { level: 3 }).textContent).toBe("The SQL could not be loaded.");
    expect(within(alert).queryByRole("heading", { level: 2 })).toBeNull();
    expect(alert.textContent).not.toContain("Nothing below");
    expect(alert.textContent).toContain("the rest of the page loaded");
  });
});
