import { useState, type FormEvent } from "react";
import type { RevisionOutput, WorkflowDraftOutput, WorkflowValidationOutput } from "../api/generated";
import {
  clearPendingWorkflowRevision, createDraftRevision, readPendingWorkflowRevision,
  readWorkflowDraft, validateWorkflowDraft, WorkflowDraftError,
} from "../api/workflow-drafts";

export function WorkflowDraftPanel({ onDenied }: { onDenied: (error: WorkflowDraftError) => void }) {
  const [recovery, setRecovery] = useState(readPendingWorkflowRevision);
  const [id, setId] = useState(() =>
    recovery !== null && recovery !== "unavailable" ? recovery.workflowId : "");
  const [draft, setDraft] = useState<WorkflowDraftOutput | null>(null);
  const [validation, setValidation] = useState<WorkflowValidationOutput | null>(null);
  const [revision, setRevision] = useState<RevisionOutput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(() => {
    if (recovery === null) return null;
    if (recovery === "unavailable") {
      return "The previous revision attempt state cannot be read. Inspect saved revisions before continuing.";
    }
    return `A previous revision attempt for workflow ${recovery.workflowId} version ${recovery.expectedVersion} may have been created. Reload the draft and inspect saved revisions; do not assume it failed.`;
  });
  const [reloadRequired, setReloadRequired] = useState(recovery !== null);
  const [uncertain, setUncertain] = useState(recovery !== null);
  const [acknowledged, setAcknowledged] = useState(false);

  function failure(value: unknown, action: "load" | "validate" | "revision") {
    if (value instanceof WorkflowDraftError && (value.status === 401 || value.status === 403)) {
      setDraft(null);
      setValidation(null);
      setRevision(null);
      setId("");
      const cleared = clearPendingWorkflowRevision();
      setRecovery(cleared ? null : "unavailable");
      setUncertain(!cleared);
      setReloadRequired(!cleared);
      setAcknowledged(false);
      if (!cleared) {
        setError("Access was denied and draft contents were cleared, but the browser could not clear its revision recovery marker.");
      }
      onDenied(value);
      return;
    }
    if (value instanceof WorkflowDraftError && value.uncertain && action === "revision") {
      setRecovery(readPendingWorkflowRevision());
      setUncertain(true);
      setReloadRequired(true);
      setAcknowledged(false);
      setError("The revision may have been created. Reload the draft and inspect saved revisions before explicitly acknowledging a possible duplicate. Do not assume it failed.");
    } else if (value instanceof WorkflowDraftError && value.status === 409) {
      setRecovery(readPendingWorkflowRevision());
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
      const currentRecovery = readPendingWorkflowRevision();
      setRecovery(currentRecovery);
      setDraft(result);
      if (currentRecovery === "unavailable") {
        setUncertain(true);
        setReloadRequired(true);
        setError("The previous revision attempt state cannot be read. Inspect saved revisions before continuing.");
      } else {
        setReloadRequired(false);
        setUncertain(currentRecovery !== null);
        setAcknowledged(false);
        setError(currentRecovery
          ? `A previous revision attempt for workflow ${currentRecovery.workflowId} version ${currentRecovery.expectedVersion} may have been created. Inspect saved revisions before creating another.`
          : null);
      }
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
      const created = await createDraftRevision(draft.workflowId, draft.version, {
        acknowledgeUncertain: acknowledged,
      });
      setRevision(created);
      const currentRecovery = readPendingWorkflowRevision();
      setRecovery(currentRecovery);
      if (currentRecovery === null) {
        setUncertain(false);
        setReloadRequired(false);
        setAcknowledged(false);
      } else {
        setUncertain(true);
        setReloadRequired(true);
        setAcknowledged(false);
        setError("The revision was saved, but its recovery marker could not be cleared. Inspect saved revisions before continuing.");
      }
    } catch (value) {
      setRecovery(readPendingWorkflowRevision());
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
        <input id="workflow-draft-id" value={id} disabled={busy || uncertain}
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
        disabled={busy}>Load draft</button>
    </form>
    {busy && <p role="status">Working with the saved draft...</p>}
    {error && <div className="review-error" role="alert"><p>{error}</p></div>}
    {uncertain && <label className="workflow-draft-acknowledge">
      <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
      I understand the prior attempt may have created a revision and a new attempt could create a duplicate.
    </label>}
    {draft && <>
      <p>Workflow <code>{draft.workflowId}</code> · saved version <strong>{draft.version}</strong></p>
      <pre className="workflow-json" tabIndex={0} aria-label="Saved draft document"><code>{draft.document}</code></pre>
      {!usableVersion && <p role="note">This draft version cannot be validated or saved as a revision by the current API.</p>}
      <div className="workflow-draft-actions">
        <button className="button button--secondary" type="button" onClick={() => void validate()}
          disabled={busy || reloadRequired || !usableVersion}>Validate saved draft</button>
        <button className="button button--primary" type="button" onClick={() => void createRevision()}
          disabled={busy || reloadRequired || (uncertain && !acknowledged) ||
            !usableVersion || !validation?.isValid || revision !== null}>Create immutable revision</button>
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
