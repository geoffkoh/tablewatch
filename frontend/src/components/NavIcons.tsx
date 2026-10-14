import type { ReactElement } from "react";

/**
 * The side navigation's icons (spec 039, P-D5): inline SVG, under the
 * chart's own rules even though they are not under `components/chart/` —
 * no `href` of any kind, no `<use>`, no inline style, classes only for
 * colour. Decorative: `aria-hidden`, `focusable="false"`; the link around
 * each one carries the accessible name.
 */
function Icon({ children, className }: { children: ReactElement; className: string }): ReactElement {
  return (
    <svg className={`nav-icon ${className}`} viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export function DashboardIcon(): ReactElement {
  return (
    <Icon className="nav-icon--dashboard">
      <>
        <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1" />
        <rect x="11" y="2.5" width="6.5" height="4" rx="1" />
        <rect x="11" y="8.5" width="6.5" height="9" rx="1" />
        <rect x="2.5" y="11" width="6.5" height="6.5" rx="1" />
      </>
    </Icon>
  );
}

export function ChecksIcon(): ReactElement {
  return (
    <Icon className="nav-icon--checks">
      <>
        <rect x="2.5" y="2.5" width="15" height="15" rx="2" />
        <path d="M6 10.5l2.6 2.6L14.5 7" fill="none" className="nav-icon__stroke" />
      </>
    </Icon>
  );
}

export function DatasetsIcon(): ReactElement {
  return (
    <Icon className="nav-icon--datasets">
      <>
        <ellipse cx="10" cy="5" rx="7" ry="2.5" />
        <path
          d="M3 5v10c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5V5"
          fill="none"
          className="nav-icon__stroke"
        />
        <path d="M3 10c0 1.38 3.13 2.5 7 2.5s7-1.12 7-2.5" fill="none" className="nav-icon__stroke" />
      </>
    </Icon>
  );
}

export function MenuIcon(): ReactElement {
  return (
    <Icon className="nav-icon--menu">
      <>
        <rect x="2.5" y="4.5" width="15" height="2" rx="1" />
        <rect x="2.5" y="9" width="15" height="2" rx="1" />
        <rect x="2.5" y="13.5" width="15" height="2" rx="1" />
      </>
    </Icon>
  );
}

export function CloseIcon(): ReactElement {
  return (
    <Icon className="nav-icon--close">
      <path
        d="M4 4l12 12M16 4L4 16"
        fill="none"
        className="nav-icon__stroke"
      />
    </Icon>
  );
}

export function CollapseIcon({ expanded }: { expanded: boolean }): ReactElement {
  return (
    <Icon className="nav-icon--collapse">
      <path d={expanded ? "M12 4l-6 6 6 6" : "M8 4l6 6-6 6"} fill="none" className="nav-icon__stroke" />
    </Icon>
  );
}
