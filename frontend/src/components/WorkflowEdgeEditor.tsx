import { useEffect, useMemo, useRef, useState } from "react";
import { appendWorkflowEdge, readWorkflowEdges, removeWorkflowEdge, replaceWorkflowEdge } from "./workflow-draft-document";

const fields = [
  ["id", "Connection ID"], ["source", "Source node ID"], ["sourcePort", "Source port"],
  ["target", "Target node ID"], ["targetPort", "Target port"],
] as const;
const empty = { id: "", source: "", sourcePort: "", target: "", targetPort: "" };

export function WorkflowEdgeEditor({ document, disabled, onDocumentChange, onPendingChange }: {
  document: string; disabled: boolean; onDocumentChange: (value: string) => void; onPendingChange?: (pending: boolean) => void;
}) {
  const [values, setValues] = useState(empty);
  const [message, setMessage] = useState<"added" | "updated" | "unchanged" | "error" | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const sourceInput = useRef<HTMLInputElement>(null);
  const added = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const removed = useRef(false);
  const [removalNotice, setRemovalNotice] = useState<string | null>(null);
  const edges = useMemo(() => readWorkflowEdges(document), [document]);
  useEffect(() => {
    if (!added.current) setMessage(null);
    added.current = false;
    if (removed.current) heading.current?.focus();
    else setRemovalNotice(null);
    removed.current = false;
  }, [document]);
  return <section aria-labelledby="workflow-connections-title">
    <h4 id="workflow-connections-title" ref={heading} tabIndex={-1}>Connections</h4>
    {edges === null ? <p role="note">Connections cannot be listed safely. You can edit the JSON directly.</p> :
      edges.length === 0 ? <p>No connections.</p> : <ul aria-label="Workflow connections">
        {edges.map((edge) => <li className="workflow-connection-item" key={edge.id}>
          <code>{edge.id}</code>: {edge.source} / {edge.sourcePort} → {edge.target} / {edge.targetPort}{" "}
          <button className="button button--secondary" type="button"
            disabled={disabled || editingId !== null || Object.values(values).some((value) => value.length > 0)}
            aria-label={`Edit connection ${edge.id}`} onClick={() => {
              setValues(edge); setEditingId(edge.id); onPendingChange?.(true); setMessage(null); setRemovalNotice(null);
              sourceInput.current?.focus();
            }}>Edit</button>{" "}
          <button className="button button--secondary" type="button" disabled={disabled || editingId !== null}
            aria-label={`Remove connection ${edge.id}`} onClick={() => {
              const updated = removeWorkflowEdge(document, edge.id);
              if (!updated) return;
              removed.current = true;
              setRemovalNotice(`Removed connection ${edge.id} locally. Save the draft to keep it.`);
              onDocumentChange(updated);
            }}>Remove</button>
        </li>)}
      </ul>}
    {removalNotice && <p role="status">{removalNotice}</p>}
    <fieldset disabled={disabled}>
    <legend>{editingId === null ? "Add connection" : "Edit connection"}</legend>
    <p>Enter node IDs and ports. Changes stay local until saved; validate the saved draft to check connections.</p>
    {fields.map(([key, label]) => <div className="schedule-create-field" key={key}>
      <label htmlFor={`workflow-edge-${key}`}>{label}</label>
      <input id={`workflow-edge-${key}`} value={values[key]} maxLength={256}
        ref={key === "source" ? sourceInput : undefined} disabled={key === "id" && editingId !== null}
        onChange={(event) => {
          const next = { ...values, [key]: event.target.value };
          setValues(next); onPendingChange?.(editingId !== null || Object.values(next).some((value) => value.length > 0)); setMessage(null);
        }} />
    </div>)}
    {(editingId !== null || Object.values(values).some((value) => value.length > 0)) &&
      <button className="button button--secondary" type="button" onClick={() => {
        setValues(empty); setEditingId(null); onPendingChange?.(false); setMessage(null);
      }}>Clear connection input</button>}
    <button className="button button--secondary" type="button" onClick={() => {
      const updated = editingId === null ? appendWorkflowEdge(document, JSON.stringify(values)) : replaceWorkflowEdge(document, editingId, JSON.stringify(values));
      if (!updated) { setMessage("error"); return; }
      const unchanged = updated === document;
      if (!unchanged) { added.current = true; onDocumentChange(updated); }
      setValues(empty);
      setEditingId(null);
      onPendingChange?.(false);
      setMessage(unchanged ? "unchanged" : editingId === null ? "added" : "updated");
    }}>{editingId === null ? "Add connection" : "Apply connection changes"}</button>
    {message === "error" && <p role="alert">Cannot {editingId === null ? "add" : "update"} connection. Check the fields, unique ID and draft size; connections with extra fields must be edited in JSON.</p>}
    {message === "added" && <p role="status">Connection added locally. Save the draft to keep it.</p>}
    {message === "updated" && <p role="status">Connection updated locally. Save the draft to keep it.</p>}
    {message === "unchanged" && <p role="status">Connection unchanged.</p>}
    </fieldset>
  </section>;
}
