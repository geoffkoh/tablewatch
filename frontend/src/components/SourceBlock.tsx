import type { ReactElement, Ref } from "react";
import { Marked } from "./Marked";

/** The widest number column the CSS sets; a longer file's numbers overflow it by a digit or so. */
export const MAX_DIGITS = 6;

/**
 * A check file's lines, numbered (spec 006, P4, P14, P16; the ui-engineer's
 * answer to Q3). Beside `CodeBlock`, not a mode of it: this block never wraps,
 * because YAML's indentation is its meaning and a wrapped line would sit under
 * the wrong number. It scrolls sideways inside itself instead.
 *
 * One `span.line` per line, blank lines included, each holding a `\n` but the
 * last, so the `<code>`'s `textContent` is `text` exactly. The numbers are CSS
 * generated content from `data-line`, so they are never selected or copied;
 * their column is as wide as `end`'s digits: `data-digits` sets the
 * `--line-digits` custom property in CSS (the CSP allows no inline style).
 */
export function SourceBlock({
  text,
  start,
  label,
  codeRef,
}: {
  /** The lines joined by `\n`, no trailing newline (`CheckSource.text`). */
  text: string;
  /** The first line's 1-based number in the file. */
  start: number;
  /** The region's accessible name. */
  label: string;
  /** The `<code>` element: what "Select all" selects (P9). */
  codeRef?: Ref<HTMLElement>;
}): ReactElement {
  // The server splits on \r\n, \r and \n only and joins with \n (security B1),
  // so \n is the one separator here; any other break character is marked.
  const lines = text.split("\n");
  const end = start + lines.length - 1;
  const digits = Math.min(String(end).length, MAX_DIGITS);
  return (
    <pre className="code-block code-block--lines" tabIndex={0} role="region" aria-label={label} data-digits={digits}>
      <code ref={codeRef}>
        {lines.map((line, i) => (
          <span key={i} className="line" data-line={start + i}>
            <Marked text={line} />
            {i < lines.length - 1 ? "\n" : null}
          </span>
        ))}
      </code>
    </pre>
  );
}
