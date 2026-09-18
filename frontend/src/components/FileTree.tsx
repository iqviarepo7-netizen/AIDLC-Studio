import type { Workflow } from "../types";

type Props = {
  workflow?: Workflow;
  selectedFile?: string;
  onSelect: (path: string) => void;
};

export function FileTree({ workflow, selectedFile, onSelect }: Props) {
  const files = workflow?.generated_files ?? workflow?.implementation?.changed_files.map((path) => ({ path, content: "" })) ?? [];

  const building = workflow?.state === "IMPLEMENTING";

  return (
    <aside className="sidebar">
      <div className="panel-title">Explorer</div>
      {!workflow && <p className="muted">Run a pipeline to inspect generated files.</p>}
      {workflow && (
        <ul className={`file-tree ${building ? "file-tree-live" : ""}`}>
          {files.map((file) => (
            <li key={file.path}>
              <button className={`${selectedFile === file.path ? "active" : ""} ${building && !file.content ? "pending-file" : ""}`} onClick={() => onSelect(file.path)}>
                {file.path}
              </button>
            </li>
          ))}
        </ul>
      )}
      {workflow?.implementation && (
        <div className="meta-block">
          <div className="panel-title">Branch</div>
          <code>{workflow.implementation.branch}</code>
        </div>
      )}
    </aside>
  );
}
