import type { ReactElement, Ref } from "react";
import { Marked } from "./Marked";

/**
 * A block of code shown as text (spec 005, P8, P12, P14): monospace, whitespace
 * kept, soft-wrapped so the page never scrolls sideways, no line numbers, no
 * highlighting. It is a focusable, labelled region, so a keyboard user can
 * reach it and scroll it if a line cannot wrap.
 */
export function CodeBlock({
  text,
  label,
  ref,
  tone = "code",
}: {
  text: string;
  /** The region's accessible name. */
  label: string;
  ref?: Ref<HTMLPreElement>;
  tone?: "code" | "error";
}): ReactElement {
  return (
    <pre ref={ref} className={`code-block code-block--${tone}`} tabIndex={0} role="region" aria-label={label}>
      <Marked text={text} />
    </pre>
  );
}
