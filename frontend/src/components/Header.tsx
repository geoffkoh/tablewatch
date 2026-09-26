import type { ReactElement } from "react";
import type { Project } from "../api/types";
import { Ago } from "./Time";

interface HeaderProps {
  project: Project | null;
  now: number;
  busy: boolean;
  onRefresh: () => void;
}

/** Project, version, the age of the check files (O7), and Refresh (O10). */
export function Header({ project, now, busy, onRefresh }: HeaderProps): ReactElement {
  return (
    <header className="app-header">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="app-header__inner">
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
            <h1 className="project-name">{project.name}</h1>
            <p className="loaded-at">
              Check files loaded <Ago iso={project.loaded_at} now={now} />
            </p>
          </div>
        )}
        {project === null && <h1 className="project-name">Overview</h1>}
        <button type="button" className="button" onClick={onRefresh} aria-busy={busy}>
          Refresh
        </button>
      </div>
    </header>
  );
}
