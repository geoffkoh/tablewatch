/**
 * The Settings page, `/settings` (spec 040 S-D6/S-D7): read-only project
 * configuration — which store this server reads, whether it is migrated,
 * which notifiers are configured and where their URL comes from, and how
 * many checks are active, disabled or retired. Never a credential, a
 * resolved environment value, the store URL or the project root (S-D2):
 * the server already withholds those, so the page only renders what it
 * is sent.
 *
 * `GET /api/v1/project` (for the shell's header and the page title, as
 * every other page) and `GET /api/v1/settings` load as two slots, plus the
 * shell's `problems` slot (§3). No form control, no button but Refresh.
 */
import { useEffect, type ReactElement } from "react";
import { getProject, getSettings } from "../api/api";
import type { CheckList, Project, Settings as SettingsData, SettingsResults } from "../api/types";
import { AppShell } from "../components/AppShell";
import { LoadError } from "../components/LoadError";
import { Ago } from "../components/Time";
import { fetchNavProblems, NAV_BACKGROUND } from "../lib/navProblems";
import { useLoads, type Requests } from "../lib/useLoads";

interface SettingsSlots {
  project: Project;
  settings: SettingsData;
  problems: CheckList;
}

const REQUESTS: Requests<SettingsSlots> = {
  project: getProject,
  settings: getSettings,
  problems: fetchNavProblems,
};

/** S-D6: the store's schema state in words. */
function schemaText(results: SettingsResults): ReactElement {
  switch (results.schema) {
    case "current":
      return <>Up to date ({results.revision})</>;
    case "older":
      return (
        <>
          Older than this tablewatch ({results.revision}; this version is at {results.head})
        </>
      );
    case "newer":
      return <>Newer than this tablewatch ({results.revision})</>;
    case "empty":
      return <>Nothing recorded yet</>;
    case "unavailable":
      return <>Could not be read</>;
  }
}

/** S-D6: whether the store is migrated by tablewatch itself. */
function migrateText(migrate: SettingsResults["migrate"]): ReactElement {
  switch (migrate) {
    case "auto":
      return <>Applied by tablewatch when a run opens the store</>;
    case "never":
      return (
        <>
          Managed outside tablewatch (<code>tablewatch store sql</code>)
        </>
      );
  }
}

/** S-D6: when the check registry is written to the store. */
function syncText(sync: SettingsResults["sync"]): ReactElement {
  switch (sync) {
    case "on_run":
      return <>On every recorded run</>;
    case "manual":
      return (
        <>
          Only by <code>tablewatch sync</code>
        </>
      );
  }
}

export function Settings(): ReactElement {
  const { slots, busy, now, reload } = useLoads(REQUESTS, NAV_BACKGROUND);
  const { project, settings, problems } = slots;
  const loadedProject = project.state === "ok" ? project.data : null;

  useEffect(() => {
    document.title = `Settings — ${loadedProject?.name ?? "tablewatch"}`;
  }, [loadedProject]);

  let status: string;
  if (busy) status = "Loading…";
  else if (project.state === "failed" || settings.state === "failed") status = "Could not load everything.";
  else status = "Up to date.";

  return (
    <AppShell
      current="settings"
      project={loadedProject}
      now={now}
      busy={busy}
      onRefresh={reload}
      problems={problems}
      projectIsHeading={false}
    >
      <p className="visually-hidden" role="status">
        {status}
      </p>
      <h1 className="check-title">Settings</h1>
      {project.state === "failed" && <LoadError what="the project" failure={project.failure} onRetry={reload} />}
      {settings.state === "loading" && <p className="loading">Loading…</p>}
      {settings.state === "failed" && <LoadError what="the settings" failure={settings.failure} onRetry={reload} />}
      {settings.state === "ok" && (
        <>
          <ProjectSection project={settings.data.project} now={now} />
          <DatasourcesSection datasources={settings.data.datasources} />
          <NotifiersSection notifiers={settings.data.notifiers} />
          <ResultsSection results={settings.data.results} />
          <ChecksSection checks={settings.data.checks} />
        </>
      )}
    </AppShell>
  );
}

function ProjectSection({ project, now }: { project: SettingsData["project"]; now: number }): ReactElement {
  return (
    <section className="panel" aria-labelledby="settings-project-heading">
      <h2 id="settings-project-heading" className="panel__title">
        Project
      </h2>
      <dl className="facts facts--wide">
        <div>
          <dt>Name</dt>{" "}
          <dd>{project.name}</dd>
        </div>
        <div>
          <dt>Check files</dt>{" "}
          <dd>
            {project.checks_path === null ? (
              <span className="quiet">Outside the project</span>
            ) : (
              <code>{project.checks_path}</code>
            )}
          </dd>
        </div>
        <div>
          <dt>tablewatch</dt>{" "}
          <dd>{project.version}</dd>
        </div>
        <div>
          <dt>Loaded</dt>{" "}
          <dd>
            <Ago iso={project.loaded_at} now={now} />
          </dd>
        </div>
      </dl>
    </section>
  );
}

function DatasourcesSection({ datasources }: { datasources: SettingsData["datasources"] }): ReactElement {
  return (
    <section className="panel" aria-labelledby="settings-datasources-heading">
      <h2 id="settings-datasources-heading" className="panel__title">
        Datasources
      </h2>
      {datasources.length === 0 ? (
        <p className="empty">No datasources.</p>
      ) : (
        <div className="table-scroll">
          <table className="check-table">
            <caption className="visually-hidden">Datasources, in configuration order</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">Datasets</th>
                <th scope="col">Checks</th>
              </tr>
            </thead>
            <tbody>
              {datasources.map((d) => (
                <tr key={d.name}>
                  <th scope="row">{d.name}</th>
                  <td>{d.type}</td>
                  <td>{d.datasets}</td>
                  <td>{d.checks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function NotifiersSection({ notifiers }: { notifiers: SettingsData["notifiers"] }): ReactElement {
  return (
    <section className="panel" aria-labelledby="settings-notifiers-heading">
      <h2 id="settings-notifiers-heading" className="panel__title">
        Notifiers
      </h2>
      {notifiers.length === 0 ? (
        <p className="empty">No notifiers configured.</p>
      ) : (
        <div className="table-scroll">
          <table className="check-table">
            <caption className="visually-hidden">Notifiers, in configuration order</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Type</th>
                <th scope="col">URL from</th>
              </tr>
            </thead>
            <tbody>
              {notifiers.map((n) => (
                <tr key={n.name}>
                  <th scope="row">{n.name}</th>
                  <td>{n.type}</td>
                  <td>
                    <code>{`\${env:${n.url_variable}}`}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ResultsSection({ results }: { results: SettingsResults }): ReactElement {
  return (
    <section className="panel" aria-labelledby="settings-results-heading">
      <h2 id="settings-results-heading" className="panel__title">
        Results store
      </h2>
      <dl className="facts facts--wide">
        <div>
          <dt>Database</dt>{" "}
          <dd>{results.dialect}</dd>
        </div>
        <div>
          <dt>Schema</dt>{" "}
          <dd>{schemaText(results)}</dd>
        </div>
        <div>
          <dt>Migrations</dt>{" "}
          <dd>{migrateText(results.migrate)}</dd>
        </div>
        <div>
          <dt>Registry sync</dt>{" "}
          <dd>{syncText(results.sync)}</dd>
        </div>
      </dl>
    </section>
  );
}

function ChecksSection({ checks }: { checks: SettingsData["checks"] }): ReactElement {
  return (
    <section className="panel" aria-labelledby="settings-checks-heading">
      <h2 id="settings-checks-heading" className="panel__title">
        Checks
      </h2>
      <dl className="facts facts--wide">
        <div>
          <dt>Active</dt>{" "}
          <dd>{checks.active}</dd>
        </div>
        <div>
          <dt>Disabled</dt>{" "}
          <dd>{checks.disabled}</dd>
        </div>
        <div>
          <dt>Retired</dt>{" "}
          <dd>{checks.retired === null ? "—" : checks.retired}</dd>
        </div>
      </dl>
    </section>
  );
}
