import { useState, type FormEvent } from "react";
import type { RevisionOutput, WorkflowDraftOutput, WorkflowValidationOutput } from "../api/generated";
import {
  createDraftRevision, readWorkflowDraft, validateWorkflowDraft, WorkflowDraftError,
} from "../api/workflow-drafts";

export function WorkflowDraftPanel({ onDenied }: { onDenied: (error: WorkflowDraftError) => void }) {
  const [id, setId] = useState("");
  const [draft, setDraft] = useState<WorkflowDraftOutput | null>(null);
  const [validation, setValidation] = useState<WorkflowValidationOutput | null>(null);
  const [revision, setRevision] = useState<RevisionOutput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadRequired, setReloadRequired] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  function failure(value: unknown, action: "load" | "validate" | "revision") {
    if (value instanceof WorkflowDraftError && (value.status === 401 || value.status === 403)) {
      setDraft(null);
      setValidation(null);
      setRevision(null);
      onDenied(value);
      return;
    }
    if (value instanceof WorkflowDraftError && value.uncertain && action === "revision") {
      setUncertain(true);
      setReloadRequired(true);
      setError("The revision may have been created. Copy the workflow ID, version and draft below before leaving or reloading; inspect the saved revision and compare its exact content and digest. Do not assume it failed.");
    } else if (value instanceof WorkflowDraftError && value.status === 409) {
      setReloadRequired(true);
      setError("The draft or revision conflicts with server state. Reload the draft and inspect saved revisions before trying again.");
    } else if (value instanceof WorkflowDraftError && value.status === 404) {
      setError("No saved draft was found for this workflow ID.");
    } else if (value instanceof WorkflowDraftError && value.status === 422) {
      setError(value.message.startsWith("Enter ") ? value.message : "The request was rejected. Check the ID, draft and size limits.");
      if (action === "revision") setValidation(null);
    } else {
      setError(value instanceof Error ? value.message : "The workflow service could not be reached.");
    }
  }

  async function load(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setValidation(null);
    setRevision(null);
    try {
      const result = await readWorkflowDraft(id);
      setDraft(result);
      setReloadRequired(false);
      setUncertain(false);
      setAcknowledged(false);
    } catch (value) {
      setDraft(null);
      failure(value, "load");
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    if (!draft || busy || reloadRequired) return;
    setBusy(true);
    setError(null);
    setValidation(null);
    setRevision(null);
    try {
      setValidation(await validateWorkflowDraft(draft.workflowId, draft.version));
    } catch (value) {
      failure(value, "validate");
    } finally {
      setBusy(false);
    }
  }

  async function createRevision() {
    if (!draft || busy || reloadRequired || !validation?.isValid) return;
    setBusy(true);
    setError(null);
    try {
      setRevision(await createDraftRevision(draft.workflowId, draft.version));
    } catch (value) {
      failure(value, "revision");
    } finally {
      setBusy(false);
    }
  }

  const usableVersion = draft !== null && draft.version < 2_147_483_647;
  return <section className="workflow-draft-panel" aria-labelledby="workflow-draft-title" aria-busy={busy}>
    <h2 id="workflow-draft-title">Saved draft</h2>
    <p>Load a draft by workflow ID, validate its saved version, and create an immutable revision. This does not run the workflow.</p>
    <form onSubmit={(event) => void load(event)} className="workflow-draft-form">
      <div className="schedule-create-field">
        <label htmlFor="workflow-draft-id">Workflow ID</label>
        <input id="workflow-draft-id" value={id} disabled={busy || (uncertain && !acknowledged)}
          onChange={(event) => {
            setId(event.target.value);
            setDraft(null);
            setValidation(null);
            setRevision(null);
            setError(null);
            setReloadRequired(false);
          }} placeholder="00000000-0000-0000-0000-000000000000" required />
      </div>
      <button className="button button--secondary" type="submit"
        disabled={busy || (uncertain && !acknowledged)}>Load draft</button>
    </form>
    {busy && <p role="status">Working with the saved draft...</p>}
    {error && <div className="review-error" role="alert"><p>{error}</p></div>}
    {uncertain && <label className="workflow-draft-acknowledge">
      <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
      I have retained the draft details needed to reconcile this uncertain result.
    </label>}
    {draft && <>
      <p>Workflow <code>{draft.workflowId}</code> · saved version <strong>{draft.version}</strong></p>
      <pre className="workflow-json" tabIndex={0} aria-label="Saved draft document"><code>{draft.document}</code></pre>
      {!usableVersion && <p role="note">This draft version cannot be validated or saved as a revision by the current API.</p>}
      <div className="workflow-draft-actions">
        <button className="button button--secondary" type="button" onClick={() => void validate()}
          disabled={busy || reloadRequired || !usableVersion}>Validate saved draft</button>
        <button className="button button--primary" type="button" onClick={() => void createRevision()}
          disabled={busy || reloadRequired || !usableVersion || !validation?.isValid || revision !== null}>Create immutable revision</button>
      </div>
      {validation?.isValid && <p role="status">Draft is valid for version {validation.draftVersion}.</p>}
      {validation && !validation.isValid && <div role="status">
        <p>Draft validation found {validation.issues.length} issue(s).</p>
        <ul>{validation.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>
          <strong>{issue.code}</strong>: {issue.message}
          {issue.nodeId && <> (node: <code>{issue.nodeId}</code>)</>}
          {issue.edgeId && <> (edge: <code>{issue.edgeId}</code>)</>}
        </li>)}</ul>
      </div>}
      {revision && <div role="status">
        <p>Revision saved: <code>{revision.revision}</code>. Execution readiness is not established.</p>
        <p>Returned SHA-256: <code className="workflow-digest">{revision.sha256}</code></p>
        <p>Returned canonical JSON:</p>
        <pre className="workflow-json" tabIndex={0} aria-label="Created revision canonical JSON"><code>{revision.canonicalJson}</code></pre>
      </div>}
    </>}
  </section>;
}
