/**
 * Invisible and direction-changing characters (spec 005, P14; security R5).
 *
 * A check file can hold characters that render as nothing or reorder the text
 * around them (a right-to-left override can make `amount < 0` display as
 * something else). The page marks each one in place without changing the
 * text: the character stays in the DOM and the marker is drawn by CSS, so
 * copying still yields the exact bytes.
 */

/** True for a code point the page marks: zero-width, bidi controls, soft hyphen, C0/C1 controls but tab and newline. */
export function isInvisible(cp: number): boolean {
  if (cp === 0x09 || cp === 0x0a) return false;
  if (cp <= 0x1f) return true; // C0 controls
  if (cp >= 0x7f && cp <= 0x9f) return true; // DEL and C1 controls
  if (cp === 0xad) return true; // soft hyphen
  if (cp >= 0x200b && cp <= 0x200f) return true; // zero-width, LRM, RLM
  if (cp >= 0x202a && cp <= 0x202e) return true; // bidi embeddings and overrides
  if (cp >= 0x2060 && cp <= 0x2069) return true; // word joiner, invisible operators, bidi isolates
  return cp === 0xfeff; // zero-width no-break space (BOM)
}

export type Segment = { kind: "text"; text: string } | { kind: "invisible"; text: string; label: string };

/** `U+202E` for a code point. */
export function codePointLabel(cp: number): string {
  return `U+${cp.toString(16).toUpperCase().padStart(4, "0")}`;
}

/** The text split into visible runs and single marked characters; joined, the segments are the text. */
export function segments(text: string): Segment[] {
  const out: Segment[] = [];
  let run = "";
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    if (isInvisible(cp)) {
      if (run !== "") out.push({ kind: "text", text: run });
      run = "";
      out.push({ kind: "invisible", text: ch, label: codePointLabel(cp) });
    } else {
      run += ch;
    }
  }
  if (run !== "") out.push({ kind: "text", text: run });
  return out;
}
