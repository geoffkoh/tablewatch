import type { ReactElement } from "react";
import { segments } from "../lib/invisible";

/**
 * Text with invisible and direction-changing characters marked in place
 * (spec 005, P14). Each such character stays in the DOM inside an isolated
 * span, so it cannot reorder the text around it, and copying yields the exact
 * text; the visible `U+XXXX` marker is drawn by CSS from `data-cp`.
 */
export function Marked({ text }: { text: string }): ReactElement {
  return (
    <>
      {segments(text).map((s, i) =>
        s.kind === "text" ? (
          s.text
        ) : (
          <span key={i} className="invisible-char" data-cp={s.label} title={`Invisible character ${s.label}`}>
            {s.text}
          </span>
        ),
      )}
    </>
  );
}
