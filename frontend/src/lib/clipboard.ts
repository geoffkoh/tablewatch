/**
 * The one module that touches the clipboard (spec 005, P9).
 *
 * The async Clipboard API needs a secure context: HTTPS, or plain HTTP on a
 * loopback address. `tablewatch serve --host 0.0.0.0` reached over plain HTTP
 * at a LAN address is not one, so the page falls back to selecting the text
 * for the user to copy by hand. There is deliberately no fallback to the
 * deprecated document copy command. If a `Permissions-Policy` header is ever added, it must keep
 * `clipboard-write=(self)`.
 */

/** True when `copyText` can work in this page. */
export function canCopy(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator !== "undefined" &&
    // Typed as always present, but undefined outside a secure context and in
    // some embedded browsers; reading it must never throw.
    typeof (navigator.clipboard as Clipboard | undefined)?.writeText === "function"
  );
}

/** Write text to the clipboard; rejects when the browser refuses. */
export function copyText(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}

/** Select every character inside an element, for the user to copy by hand. */
export function selectContents(element: Element): void {
  const selection = window.getSelection();
  if (selection === null) return;
  selection.selectAllChildren(element);
}
