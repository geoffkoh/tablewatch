/**
 * "Check changes" wording (spec 042 K-D4).
 */
import { describe, expect, it } from "vitest";
import { checkChangeText } from "../lib/checkChanges";
import { makeCheckChange } from "./fixtures/dashboard";

describe("checkChangeText", () => {
  it.each([
    ["added", "Added"],
    ["disabled", "Disabled"],
    ["retired", "Retired"],
    ["enabled", "Enabled again"],
  ] as const)("%s reads %s", (kind, expected) => {
    expect(checkChangeText(makeCheckChange({ kind, version: null }))).toBe(expected);
  });

  it("names the new version for a redefined check", () => {
    expect(checkChangeText(makeCheckChange({ kind: "redefined", version: 3 }))).toBe("Definition changed (version 3)");
  });
});
