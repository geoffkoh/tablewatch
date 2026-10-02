import type { ReactElement } from "react";
import type { CheckSummary } from "../api/types";
import { countsText, hasProblems, type FileNode, type FolderNode, type TreeNode } from "../lib/explorer";
import { checkHref } from "../lib/route";
import { statusOf } from "../lib/status";
import { ResultValue } from "./LatestResult";
import { StatusBadge } from "./StatusIcon";

/**
 * The `checks/` tree (spec 015): nested lists, each folder and file a native
 * `<details>` so it opens by keyboard (E5). A node with a fail, error or warn
 * is open on load; while filtering, every node is open (E7).
 */

function CheckRow({ check }: { check: CheckSummary }): ReactElement {
  const status = statusOf(check);
  const latest = check.latest;
  // The measured value for pass, warn and fail only: an error's "—" is not a value (§4.5).
  const measured =
    latest !== null && (latest.outcome === "pass" || latest.outcome === "warn" || latest.outcome === "fail")
      ? latest
      : null;
  return (
    <li className={`tree__check row--${status}`} data-check-id={check.id} data-status={status}>
      <StatusBadge status={status} />
      <span className="tree__check-text">
        <a className="check__name" href={checkHref(check.id)}>
          {check.name}
        </a>{" "}
        {check.expression !== check.name && <code className="check__expression">{check.expression}</code>}
      </span>
      {measured !== null && (
        <span className="tree__value">
          <ResultValue result={measured} />
        </span>
      )}
    </li>
  );
}

function Counts({ node }: { node: TreeNode }): ReactElement {
  return <span className="tree__counts">{countsText(node.counts)}</span>;
}

function FileItem({ file, open }: { file: FileNode; open: boolean }): ReactElement {
  return (
    <li className="tree__file" data-path={file.path}>
      <details open={open || hasProblems(file.counts)}>
        <summary>
          <span className="tree__label">
            <span className="tree__name">{file.name}</span>
            {file.datasets.map((dataset) => (
              <span key={dataset} className="tree__dataset">
                {" "}
                {dataset}
              </span>
            ))}
          </span>{" "}
          <Counts node={file} />
        </summary>
        <ul className="tree__checks">
          {file.checks.map((check) => (
            <CheckRow key={check.id} check={check} />
          ))}
        </ul>
      </details>
    </li>
  );
}

function Children({ nodes, open }: { nodes: readonly TreeNode[]; open: boolean }): ReactElement {
  return (
    <ul className="tree__children">
      {nodes.map((node) =>
        node.kind === "file" ? (
          <FileItem key={node.path} file={node} open={open} />
        ) : (
          <FolderItem key={node.path} folder={node} open={open} />
        ),
      )}
    </ul>
  );
}

function FolderItem({ folder, open }: { folder: FolderNode; open: boolean }): ReactElement {
  return (
    <li className="tree__folder" data-path={folder.path}>
      <details open={open || hasProblems(folder.counts)}>
        <summary>
          <span className="tree__label">
            <span className="tree__name">{folder.name}</span>
          </span>{" "}
          <Counts node={folder} />
        </summary>
        <Children nodes={folder.children} open={open} />
      </details>
    </li>
  );
}

/**
 * The tree. A named root (`checks/`) is the one top node; an unnamed root
 * (files under several top folders) shows its children at the top level,
 * after a line with its counts. `filtering` opens every node.
 */
export function ExplorerTree({ root, filtering }: { root: FolderNode; filtering: boolean }): ReactElement {
  if (root.name === "") {
    return (
      <div className="tree">
        <p className="tree__total">
          <Counts node={root} />
        </p>
        <Children nodes={root.children} open={filtering} />
      </div>
    );
  }
  return (
    <div className="tree">
      <ul className="tree__children">
        <FolderItem folder={root} open={filtering} />
      </ul>
    </div>
  );
}
