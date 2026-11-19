import { useState, type FormEvent } from "react";
import type { RevisionOutput, WorkflowDraftOutput, WorkflowValidationOutput } from "../api/generated";
import {
  clearPendingWorkflowRevision, createDraftRevision, readPendingWorkflowRevision,
  readWorkflowDraft, saveWorkflowDraft, validateWorkflowDraft, WorkflowDraftError,
} from "../api/workflow-drafts";

type LoadedWorkflowDraftProps = {
  draft: WorkflowDraftOutput;
  document: string;
  saveNotice: string | null;
  busy: boolean;
  reloadRequired: boolean;
  validation: WorkflowValidationOutput | null;
  revision: RevisionOutput | null;
  uncertain: boolean;
  acknowledged: boolean;
  onDocumentChange: (value: string) => void;
  onSave: () => Promise<void>;
  onDiscard: () => void;
  onValidate: () => Promise<void>;
  onCreateRevision: () => Promise<void>;
};

function LoadedWorkflowDraft({
  draft, document, saveNotice, busy, reloadRequired, validation, revision,
  uncertain, acknowledged, onDocumentChange, onSave, onDiscard, onValidate,
  onCreateRevision,
}: LoadedWorkflowDraftProps) {
  const usableVersion = draft.version < 2_147_483_647;
  const unsavedChanges = document !== draft.document;
  return <>
    <p>Workflow <code>{draft.workflowId}</code> · saved version <strong>{draft.version}</strong></p>
    <label className="workflow-document-label" htmlFor="workflow-draft-document">Workflow draft JSON</label>
    <p id="workflow-draft-editor-help">Edit the JSON directly. Changes are local until saved.</p>
    <textarea id="workflow-draft-document" className="workflow-json workflow-json-editor"
      aria-describedby="workflow-draft-editor-help" value={document}
      disabled={busy || reloadRequired} spellCheck={false}
      onChange={(event) => onDocumentChange(event.target.value)} />
    {unsavedChanges && <p role="status">Unsaved changes. Save before validating or creating a revision.</p>}
    {saveNotice && <p role="status">{saveNotice}</p>}
    {!usableVersion && <p role="note">This draft version cannot be validated or saved as a revision by the current API.</p>}
    <div className="workflow-draft-actions">
      {unsavedChanges && !reloadRequired && <button className="button button--secondary" type="button"
        onClick={onDiscard}>Discard edits</button>}
      <button className="button button--secondary" type="button" onClick={() => void onSave()}
        disabled={busy || reloadRequired || !usableVersion || !unsavedChanges}>Save draft</button>
      <button className="button button--secondary" type="button" onClick={() => void onValidate()}
        disabled={busy || reloadRequired || !usableVersion || unsavedChanges}>Validate saved draft</button>
      <button className="button button--primary" type="button" onClick={() => void onCreateRevision()}
        disabled={busy || reloadRequired || (uncertain && !acknowledged) ||
          !usableVersion || unsavedChanges || !validation?.isValid || revision !== null}>Create immutable revision</button>
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
  </>;
}

export function WorkflowDraftPanel({ onDenied }: { onDenied: (error: WorkflowDraftError) => void }) {
  const [recovery, setRecovery] = useState(readPendingWorkflowRevision);
  const [id, setId] = useState(() =>
    recovery !== null && recovery !== "unavailable" ? recovery.workflowId : "");
  const [draft, setDraft] = useState<WorkflowDraftOutput | null>(null);
  const [editorDocument, setEditorDocument] = useState("");
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
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

  function failure(value: unknown, action: "load" | "save" | "validate" | "revision") {
    if (value instanceof WorkflowDraftError && (value.status === 401 || value.status === 403)) {
      setDraft(null);
      setEditorDocument("");
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
    } else if (value instanceof WorkflowDraftError && value.uncertain && action === "save") {
      setReloadRequired(true);
      setError("The draft may have been saved. Reload the saved draft to reconcile its version before continuing.");
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
      setEditorDocument(result.document);
      setSaveNotice(null);
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
      failure(value, "load");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!draft || busy || reloadRequired || editorDocument === draft.document) return;
    setBusy(true);
    setError(null);
    setSaveNotice(null);
    setValidation(null);
    setRevision(null);
    try {
      const saved = await saveWorkflowDraft(draft.workflowId, editorDocument, draft.version);
      setDraft(saved);
      setEditorDocument(saved.document);
      setSaveNotice(`Draft saved as version ${saved.version}.`);
    } catch (value) {
      failure(value, "save");
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    if (!draft || busy || reloadRequired || editorDocument !== draft.document) return;
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
    if (!draft || busy || reloadRequired || editorDocument !== draft.document || !validation?.isValid) return;
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

  const unsavedChanges = draft !== null && editorDocument !== draft.document;
  return <section className="workflow-draft-panel" aria-labelledby="workflow-draft-title" aria-busy={busy}>
    <h2 id="workflow-draft-title">Saved draft</h2>
    <p>Edit a saved JSON document and save it as a new draft version. Validation and immutable revision creation use the saved version only; this does not run the workflow.</p>
    <form onSubmit={(event) => void load(event)} className="workflow-draft-form">
      <div className="schedule-create-field">
        <label htmlFor="workflow-draft-id">Workflow ID</label>
        <input id="workflow-draft-id" value={id} disabled={busy || uncertain || unsavedChanges || reloadRequired}
          onChange={(event) => {
            setId(event.target.value);
            setDraft(null);
            setEditorDocument("");
            setSaveNotice(null);
            setValidation(null);
            setRevision(null);
            setError(null);
            setReloadRequired(false);
          }} placeholder="00000000-0000-0000-0000-000000000000" required />
      </div>
      <button className="button button--secondary" type="submit"
        disabled={busy || (unsavedChanges && !reloadRequired)}>
        {reloadRequired ? "Reload saved draft" : "Load draft"}
      </button>
    </form>
    {busy && <p role="status">Working with the saved draft...</p>}
    {error && <div className="review-error" role="alert"><p>{error}</p></div>}
    {uncertain && <label className="workflow-draft-acknowledge">
      <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
      I understand the prior attempt may have created a revision and a new attempt could create a duplicate.
    </label>}
    {draft && <LoadedWorkflowDraft draft={draft} document={editorDocument} saveNotice={saveNotice}
      busy={busy} reloadRequired={reloadRequired} validation={validation} revision={revision}
      uncertain={uncertain} acknowledged={acknowledged}
      onDocumentChange={(value) => {
        setEditorDocument(value);
        setSaveNotice(null);
        setValidation(null);
        setRevision(null);
        setError(null);
      }}
      onSave={save}
      onDiscard={() => {
        setEditorDocument(draft.document);
        setSaveNotice("Unsaved changes were discarded. The saved version is unchanged.");
        setValidation(null);
        setRevision(null);
        setError(null);
      }}
      onValidate={validate}
      onCreateRevision={createRevision} />}
  </section>;
}
