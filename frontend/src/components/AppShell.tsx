/**
 * The shell every page renders inside (spec 039, P-D2): the top bar
 * (`Header`, unchanged: brand, project, Refresh, and now "Menu" on narrow
 * screens), a `<nav aria-label="Sections">` of the sections built so far
 * (Dashboard, Checks, Datasets, Settings — P-D1, spec 040 S-D6), and `<main id="main">` holding the
 * page's own content. Not found uses it too, with no current section and no
 * problems count (it makes no request, W3).
 *
 * The nav is a left column on wide screens, collapsible to an icon rail
 * (P-D4); the collapsed choice is remembered in web storage through
 * `lib/navPreference.ts`, the only module allowed to touch it (P-D5). On
 * narrow screens the same `<nav>` becomes a drawer, opened by the header's
 * "Menu" button; both mechanisms live in the DOM together and CSS alone
 * decides which is visible at a given width (jsdom cannot lay out, so which
 * one a human sees on a given screen is for VERIFY; the elements and their
 * behaviour are tested here regardless of viewport).
 */
import { useCallback, useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from "react";
import type { CheckList, Project } from "../api/types";
import { navProblemsCount } from "../lib/navProblems";
import { readNavCollapsed, writeNavCollapsed } from "../lib/navPreference";
import type { Load } from "../lib/useLoads";
import { Header } from "./Header";
import { ChecksIcon, CloseIcon, CollapseIcon, DashboardIcon, DatasetsIcon, SettingsIcon } from "./NavIcons";

export type Section = "dashboard" | "checks" | "datasets" | "settings";

interface SectionDef {
  key: Section;
  label: string;
  href: string;
  Icon: () => ReactElement;
}

/** Dashboard, Checks, Datasets, Settings, in that order (P-D1, N1; spec 040 S-D6). Runs and Alerts are not built yet. */
const SECTIONS: readonly SectionDef[] = [
  { key: "dashboard", label: "Dashboard", href: "/", Icon: DashboardIcon },
  { key: "checks", label: "Checks", href: "/checks", Icon: ChecksIcon },
  { key: "datasets", label: "Datasets", href: "/datasets", Icon: DatasetsIcon },
  { key: "settings", label: "Settings", href: "/settings", Icon: SettingsIcon },
];

export function AppShell({
  current,
  project,
  now,
  busy,
  onRefresh,
  problems = null,
  projectIsHeading = true,
  children,
}: {
  /** The section this page belongs to; null for Not found (no link gets `aria-current`). */
  current: Section | null;
  project: Project | null;
  now: number;
  busy: boolean;
  onRefresh: () => void;
  /** The page's own `problems` slot; null when the page makes no request at all (Not found). */
  problems?: Load<CheckList> | null;
  projectIsHeading?: boolean;
  children: ReactNode;
}): ReactElement {
  const navId = useId();
  const [collapsed, setCollapsed] = useState(() => readNavCollapsed());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const firstLinkRef = useRef<HTMLAnchorElement | null>(null);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    menuButtonRef.current?.focus();
  }, []);

  // Opening the drawer moves focus into it (P-D4); Escape closes it from
  // anywhere and returns focus to "Menu".
  useEffect(() => {
    if (!drawerOpen) return;
    firstLinkRef.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") closeDrawer();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [drawerOpen, closeDrawer]);

  const count = navProblemsCount(problems);

  const toggleCollapsed = (): void => {
    const next = !collapsed;
    setCollapsed(next);
    writeNavCollapsed(next);
  };

  return (
    <>
      <Header
        project={project}
        now={now}
        busy={busy}
        onRefresh={onRefresh}
        projectIsHeading={projectIsHeading}
        onMenu={() => {
          setDrawerOpen(true);
        }}
        menuExpanded={drawerOpen}
        menuControls={navId}
        ref={menuButtonRef}
      />
      <div className={`app-shell${collapsed ? " app-shell--rail" : ""}`}>
        {drawerOpen && <div className="nav-backdrop" onClick={closeDrawer} />}
        <nav
          id={navId}
          aria-label="Sections"
          className={`app-nav${collapsed ? " app-nav--rail" : ""}${drawerOpen ? " app-nav--open" : ""}`}
        >
          <button type="button" className="nav-close" onClick={closeDrawer}>
            <CloseIcon />
            <span className="visually-hidden">Close navigation</span>
          </button>
          <ul className="app-nav__list">
            {SECTIONS.map(({ key, label, href, Icon }, index) => {
              const isChecks = key === "checks";
              const badge = isChecks ? count : null;
              return (
                <li key={key}>
                  <a
                    href={href}
                    ref={index === 0 ? firstLinkRef : undefined}
                    aria-current={key === current ? "page" : undefined}
                    aria-label={badge !== null ? `${label}, ${String(badge)} failing or in error` : undefined}
                    className="app-nav__link"
                  >
                    <Icon />
                    <span className="nav-label">{label}</span>
                    <span className="nav-tooltip" aria-hidden="true">
                      {label}
                    </span>
                    {badge !== null && (
                      <span className="nav-badge" aria-hidden="true">
                        {badge}
                      </span>
                    )}
                  </a>
                </li>
              );
            })}
          </ul>
          <button
            type="button"
            className="nav-collapse"
            aria-expanded={!collapsed}
            aria-controls={navId}
            onClick={toggleCollapsed}
          >
            <CollapseIcon expanded={!collapsed} />
            <span className="nav-label">{collapsed ? "Expand navigation" : "Collapse navigation"}</span>
          </button>
        </nav>
        <main id="main" className="page" tabIndex={-1} aria-busy={busy}>
          {children}
        </main>
      </div>
    </>
  );
}
