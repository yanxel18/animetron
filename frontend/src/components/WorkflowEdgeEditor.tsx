import { useEffect, useRef, useState } from "react";
import { appendWorkflowEdge } from "./workflow-draft-document";

const fields = [
  ["id", "Connection ID"], ["source", "Source node ID"], ["sourcePort", "Source port"],
  ["target", "Target node ID"], ["targetPort", "Target port"],
] as const;
const empty = { id: "", source: "", sourcePort: "", target: "", targetPort: "" };

export function WorkflowEdgeEditor({ document, disabled, onDocumentChange }: {
  document: string; disabled: boolean; onDocumentChange: (value: string) => void;
}) {
  const [values, setValues] = useState(empty);
  const [message, setMessage] = useState<"added" | "error" | null>(null);
  const added = useRef(false);
  useEffect(() => {
    if (!added.current) setMessage(null);
    added.current = false;
  }, [document]);
  return <fieldset disabled={disabled}>
    <legend>Add connection</legend>
    <p>Enter node IDs and ports. Changes stay local until saved; validate the saved draft to check connections.</p>
    {fields.map(([key, label]) => <div className="schedule-create-field" key={key}>
      <label htmlFor={`workflow-edge-${key}`}>{label}</label>
      <input id={`workflow-edge-${key}`} value={values[key]} maxLength={256}
        onChange={(event) => { setValues({ ...values, [key]: event.target.value }); setMessage(null); }} />
    </div>)}
    <button className="button button--secondary" type="button" onClick={() => {
      const updated = appendWorkflowEdge(document, JSON.stringify(values));
      if (!updated) { setMessage("error"); return; }
      added.current = true;
      onDocumentChange(updated);
      setValues(empty);
      setMessage("added");
    }}>Add connection</button>
    {message === "error" && <p role="alert">Cannot add connection. Check all fields, unique ID and draft size.</p>}
    {message === "added" && <p role="status">Connection added locally. Save the draft to keep it.</p>}
  </fieldset>;
}
