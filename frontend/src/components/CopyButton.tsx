import { useEffect, useState, type ReactElement, type RefObject } from "react";
import { canCopy, copyText, selectContents } from "../lib/clipboard";

/** How long "Copied" stays (spec 005, P9). */
export const COPIED_MS = 2000;

type State = "idle" | "copied" | "failed";

/**
 * Copies `text` (the API's string, never the DOM) to the clipboard. Where the
 * page cannot copy (not a secure context) it becomes "Select all", which
 * selects `target`'s text for the user to copy by hand.
 */
export function CopyButton({
  text,
  name,
  target,
}: {
  text: string;
  /** What is copied, as in "the scan": the button reads "Copy the scan". */
  name: string;
  target: RefObject<HTMLElement | null>;
}): ReactElement {
  const [copyable] = useState(canCopy);
  const [state, setState] = useState<State>("idle");

  useEffect(() => {
    if (state !== "copied") return;
    const timer = window.setTimeout(() => {
      setState("idle");
    }, COPIED_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [state]);

  if (!copyable) {
    return (
      <button
        type="button"
        className="button button--small"
        aria-label={`Select all of ${name}`}
        onClick={() => {
          if (target.current !== null) selectContents(target.current);
        }}
      >
        Select all
      </button>
    );
  }

  const copy = (): void => {
    copyText(text).then(
      () => {
        setState("copied");
      },
      () => {
        setState("failed");
      },
    );
  };

  return (
    <span className="copy">
      <button type="button" className="button button--small" onClick={copy}>
        Copy {name}
      </button>
      <span className="copy__status" aria-live="polite">
        {state === "copied" ? "Copied" : state === "failed" ? "Could not copy. Select the text and copy it." : ""}
      </span>
    </span>
  );
}
