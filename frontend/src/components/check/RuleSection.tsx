import type { ReactElement } from "react";
import type { CheckDetail, Project } from "../../api/types";
import { ruleParts } from "../../lib/rule";
import { Ago } from "../Time";

/** The current rule from the check files, and a note when no run has used it yet. */
export function RuleSection({
  check,
  project,
  pending,
  now,
}: {
  check: CheckDetail;
  project: Project | null;
  pending: boolean;
  now: number;
}): ReactElement {
  return (
    <section className="panel" aria-labelledby="rule-heading">
      <h2 id="rule-heading" className="panel__title">
        Rule
      </h2>
      <dl className="rule">
        {ruleParts(check.rule).map((p) => (
          <div key={p.role} data-role={p.role}>
            <dt>{p.label}</dt>{" "}
            <dd>
              <code>{p.condition.text}</code>
            </dd>
          </div>
        ))}
      </dl>
      <p className="caption">
        The current rule, from the check files
        {project !== null && (
          <>
            {" "}
            loaded <Ago iso={project.loaded_at} now={now} />
          </>
        )}
        .
      </p>
      {pending && (
        <p className="pending-note" data-note="pending-rule">
          No run has used this rule yet. The results below were judged by an earlier rule.
        </p>
      )}
    </section>
  );
}
