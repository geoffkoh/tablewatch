import { useState, type ReactElement } from "react";
import { collapsedOptions, FACET_LEGENDS, type FacetKey, type FacetOption } from "../lib/explorer";

/**
 * One of the explorer's Tag, Owner and Datasource filters (spec 016): a
 * `<fieldset>` built like Status, one checkbox per value labelled with the
 * value and a count. Values are rendered as text only (F2, §9). A filter with
 * more than 10 values shows the 10 with the highest counts, every ticked one,
 * and a "Show all N" button (F15).
 */
export function FacetFilter({
  facet,
  options,
  onChange,
}: {
  facet: FacetKey;
  options: readonly FacetOption[];
  onChange: (values: string[]) => void;
}): ReactElement {
  const [expanded, setExpanded] = useState(false);
  const collapsed = collapsedOptions(options);
  const shown = expanded ? options : collapsed;
  const selected = options.filter((o) => o.checked).map((o) => o.value);
  return (
    <fieldset className="status-filter facet-filter" data-facet={facet}>
      <legend className="status-filter__legend">{FACET_LEGENDS[facet]}</legend>
      {shown.map((option) => (
        <label key={option.value} className={`facet-toggle${option.value === "" ? " facet-toggle--none" : ""}`}>
          <input
            type="checkbox"
            checked={option.checked}
            onChange={() => {
              onChange(
                option.checked ? selected.filter((v) => v !== option.value) : [...selected, option.value],
              );
            }}
          />
          <span className="facet-toggle__label">{option.label}</span>
          {option.note !== null && (
            <>
              {" "}
              <span className="facet-toggle__note">{option.note}</span>
            </>
          )}{" "}
          <span className="status-toggle__count">{option.count}</span>
        </label>
      ))}
      {collapsed.length < options.length && (
        <button
          type="button"
          className="button button--small facet-filter__more"
          aria-expanded={expanded}
          onClick={() => {
            setExpanded((prev) => !prev);
          }}
        >
          {expanded ? "Show fewer" : `Show all ${String(options.length)}`}
        </button>
      )}
    </fieldset>
  );
}
