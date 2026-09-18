import Editor from "@monaco-editor/react";

type Props = {
  path?: string;
  content: string;
};

function languageForPath(path?: string) {
  if (!path) return "plaintext";
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".ts") || path.endsWith(".tsx")) return "typescript";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".md")) return "markdown";
  if (path.endsWith(".yaml") || path.endsWith(".yml")) return "yaml";
  return "plaintext";
}

export function CodeEditor({ path, content }: Props) {
  if (!path) {
    return (
      <section className="editor-pane editor-empty">
        <div className="editor-tab">No file selected</div>
        <div className="editor-placeholder">
          <p>Generated files will appear here after implementation.</p>
          <span>Select a file from the explorer when available.</span>
        </div>
      </section>
    );
  }

  return (
    <section className="editor-pane">
      <div className="editor-tab">{path}</div>
      <div className="editor-body">
        <Editor
          height="100%"
          theme="vs-dark"
          language={languageForPath(path)}
          value={content || "// Loading file content..."}
          loading={<div className="editor-placeholder compact">Loading editor...</div>}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontFamily: "JetBrains Mono, ui-monospace, monospace",
            fontSize: 13,
            scrollBeyondLastLine: false,
            wordWrap: "on",
          }}
        />
      </div>
    </section>
  );
}
