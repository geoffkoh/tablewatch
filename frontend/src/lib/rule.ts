/**
 * A check's rule in words (spec 004 D3). The condition is always the API's
 * `text`: the page never formats a threshold from its numbers.
 */
import type { Condition, Rule } from "../api/types";

export type RuleRole = "expect" | "warn" | "fail";

export interface RulePart {
  role: RuleRole;
  label: string;
  condition: Condition;
}

const LABEL: Readonly<Record<RuleRole, string>> = {
  expect: "Expected",
  warn: "Warn when",
  fail: "Fail when",
};

/** "Expected < 5%", or "Warn when > 1d" and "Fail when > 7d". */
export function ruleParts(rule: Rule): RulePart[] {
  const parts: RulePart[] = [];
  for (const role of ["expect", "warn", "fail"] as const) {
    const condition = rule[role];
    if (condition !== null) parts.push({ role, label: LABEL[role], condition });
  }
  return parts;
}

/** One line: "Expected < 5%", "Warn when > 1d · Fail when > 7d". */
export function ruleSentence(rule: Rule): string {
  return ruleParts(rule)
    .map((p) => `${p.label} ${p.condition.text}`)
    .join(" · ");
}

/** The numbers a condition's boundary lines sit at. */
export function boundaryValues(condition: Condition): number[] {
  if (condition.kind === "compare") return [condition.value];
  return condition.low === condition.high ? [condition.low] : [condition.low, condition.high];
}

/** Every boundary of a rule. */
export function ruleBoundaries(rule: Rule): number[] {
  return ruleParts(rule).flatMap((p) => boundaryValues(p.condition));
}
