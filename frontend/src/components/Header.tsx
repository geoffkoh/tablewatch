import { forwardRef, type ReactElement } from "react";
import type { Project } from "../api/types";
import { MenuIcon } from "./NavIcons";
import { Ago } from "./Time";

interface HeaderProps {
  project: Project | null;
  now: number;
  busy: boolean;
  onRefresh: () => void;
  /**
   * The overview's `<h1>` is the project name. Other pages have their own
   * `<h1>` in the main content, so the project name is a paragraph there.
   */
  projectIsHeading?: boolean;
  /**
   * Opens the navigation drawer (spec 039, P-D4). Shown only on narrow
   * screens (CSS); the button is always in the DOM so it is reachable by
   * keyboard regardless of layout.
   */
  onMenu?: () => void;
  /** Whether the drawer "Menu" opens is open, and its element id (N7). */
  menuExpanded?: boolean;
  menuControls?: string;
}

/**
 * Project, version, the age of the check files (O7), and Refresh (O10). The
 * "Menu" button (spec 039) opens the side navigation as a drawer on narrow
 * screens; `ref` is the button `AppShell` returns focus to when it closes.
 */
export const Header = forwardRef<HTMLButtonElement, HeaderProps>(function Header(
  { project, now, busy, onRefresh, projectIsHeading = true, onMenu, menuExpanded = false, menuControls },
  menuRef,
): ReactElement {
  return (
    <header className="app-header">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="app-header__inner">
        {onMenu !== undefined && (
          <button
            type="button"
            ref={menuRef}
            className="button nav-menu"
            onClick={onMenu}
            aria-expanded={menuExpanded}
            aria-controls={menuControls}
          >
            <MenuIcon /> Menu
          </button>
        )}
        <p className="brand">
          <span className="brand__product">tablewatch</span>
          {project !== null && (
            <>
              {" "}
              <span className="brand__version">{project.version}</span>
            </>
          )}
        </p>
        {project !== null && (
          <div className="app-header__project">
            {projectIsHeading ? (
              <h1 className="project-name">{project.name}</h1>
            ) : (
              <p className="project-name">{project.name}</p>
            )}
            <p className="loaded-at">
              Check files loaded <Ago iso={project.loaded_at} now={now} />
            </p>
          </div>
        )}
        {project === null && projectIsHeading && <h1 className="project-name">Overview</h1>}
        {project === null && !projectIsHeading && <span className="app-header__spacer" />}
        <button type="button" className="button" onClick={onRefresh} aria-busy={busy}>
          Refresh
        </button>
      </div>
    </header>
  );
});
