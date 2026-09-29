/**
 * A check's rule in words (spec 004 D3). A condition is always shown as the
 * API's `text`, with one exception (decision 12, extended by spec 012): each
 * of a `between`'s two boundary lines on the chart says which end it is, an
 * operator and that end's number (`>= 50`, `<= 60`), formatted by the caller.
 * `text` is never parsed to recover the numbers as written.
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

/**
 * What each boundary line of a condition is labelled (spec 012 B1–B5). A
 * compare line, and a `between` whose ends are equal (one line), keep the
 * condition's `text`. A two-line `between` labels each end with the side where
 * the condition holds: inclusive `>=` / `<=` for `between` (as `Between.holds`
 * in `src/tablewatch/dsl/ast.py`), strict `<` / `>` for `not between`. ASCII,
 * as the DSL writes operators and every other rule text on the page reads.
 */
export function boundaryLabels(condition: Condition, format: (value: number) => string): { value: number; label: string }[] {
  if (condition.kind === "compare") return [{ value: condition.value, label: condition.text }];
  if (condition.low === condition.high) return [{ value: condition.low, label: condition.text }];
  const [low, high] = condition.negated ? ["<", ">"] : [">=", "<="];
  return [
    { value: condition.low, label: `${low} ${format(condition.low)}` },
    { value: condition.high, label: `${high} ${format(condition.high)}` },
  ];
}

/** Every boundary of a rule. */
export function ruleBoundaries(rule: Rule): number[] {
  return ruleParts(rule).flatMap((p) => boundaryValues(p.condition));
}
