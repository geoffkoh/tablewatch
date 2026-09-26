import type { ReactElement } from "react";
import type { Diagnostic, Project } from "../api/types";

export const PROBLEMS_ID = "project-problems";

function where(d: Diagnostic): string | null {
  return d.location === null ? null : `${d.location.file}:${String(d.location.line)}:${String(d.location.column)}`;
}

function DiagnosticList({ items }: { items: readonly Diagnostic[] }): ReactElement {
  return (
    <ul className="diagnostics">
      {items.map((d, i) => {
        const at = where(d);
        return (
          <li key={`${at ?? "project"}-${String(i)}`}>
            {at !== null && (
              <>
                <code className="diagnostic__at">{at}</code>{" "}
              </>
            )}
            <span className="diagnostic__message">{d.message}</span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The banner for a project that did not load cleanly (O6). The UI cannot
 * know how many checks a broken file held, so it says they *may* be missing
 * and never states a number.
 */
export function ProjectProblems({ project }: { project: Project }): ReactElement | null {
  const errors = project.diagnostics.filter((d) => d.severity === "error");
  const warnings = project.diagnostics.filter((d) => d.severity === "warning");

  if (project.ok) {
    if (warnings.length === 0) return null;
    return (
      <details className="notice">
        <summary>
          {warnings.length === 1 ? "1 warning" : `${String(warnings.length)} warnings`} in the check files
        </summary>
        <DiagnosticList items={warnings} />
      </details>
    );
  }

  const files = new Set(errors.flatMap((d) => (d.location === null ? [] : [d.location.file])));
  const plural = files.size > 1;
  return (
    <section id={PROBLEMS_ID} className="banner" aria-labelledby="problems-heading" tabIndex={-1}>
      <h2 id="problems-heading" className="banner__title">
        {plural ? "Check files have errors" : "A check file has errors"}
      </h2>
      <p>
        Checks from {plural ? "these files" : "this file"} may be missing from this page and from
        every count on it, so the counts are incomplete.
      </p>
      <DiagnosticList items={errors} />
      {warnings.length > 0 && (
        <>
          <h3 className="banner__subtitle">Warnings</h3>
          <DiagnosticList items={warnings} />
        </>
      )}
      <p className="banner__hint">
        <code>tablewatch serve</code> reads the check files once, when it starts. Fix the{" "}
        {plural ? "files" : "file"} and restart it.
      </p>
    </section>
  );
}
