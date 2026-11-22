import { useRef, useState, type FormEvent } from "react";
import type { RevisionOutput, WorkflowDraftOutput, WorkflowValidationOutput } from "../api/generated";
import {
  acknowledgeDraftCreation, clearPendingWorkflowRevision, createDraftRevision, createWorkflowDraft,
  readPendingDraftCreation, readPendingWorkflowRevision, reconcileDraftCreation,
  readWorkflowDraft, saveWorkflowDraft, validateWorkflowDraft, WorkflowDraftError,
} from "../api/workflow-drafts";
import { WorkflowNodeOrder } from "./WorkflowNodeOrder";

function WorkflowDraftCreation({ onDenied, busy, setBusy, blocked }: {
  onDenied: (error: WorkflowDraftError) => void;
  busy: boolean;
  setBusy: (value: boolean) => void;
  blocked: boolean;
}) {
  const [pending, setPending] = useState(readPendingDraftCreation);
  const [id, setId] = useState(() => pending && pending !== "unavailable" ? pending : "");
  const [retryAllowed, setRetryAllowed] = useState(false);
  const [found, setFound] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const canGenerateId = typeof globalThis.crypto?.randomUUID === "function";
  const [error, setError] = useState<string | null>(() =>
    pending === "unavailable"
      ? "Draft creation recovery is unavailable in this browser. No new draft can be created."
      : pending ? "A draft may have been created. Check the same ID before continuing." : null);

  function failure(value: unknown, action: "create" | "check") {
    const current = readPendingDraftCreation();
    setPending(current);
    setRetryAllowed(false);
    setFound(false);
    if (current && current !== "unavailable") setId(current);
    if (value instanceof WorkflowDraftError && (value.status === 401 || value.status === 403)) {
      setError("Owner access is required to work with drafts.");
      onDenied(value);
    } else if (current === "unavailable") {
      setError("Draft creation recovery is unavailable in this browser. No new draft can be created.");
    } else if (action === "check" && value instanceof WorkflowDraftError && value.status === 404) {
      setRetryAllowed(true);
      setError("Draft not found. The earlier request may still complete; you may retry only the same ID.");
    } else if (current && value instanceof WorkflowDraftError && (value.uncertain || value.status === 409)) {
      setError("A draft may have been created or already exists. Check the same ID before continuing.");
    } else {
      setError(value instanceof Error ? value.message : "The workflow service could not be reached.");
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy || blocked || pending === "unavailable" || (pending !== null && !retryAllowed)) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    const retryAfterCheck = retryAllowed;
    setRetryAllowed(false);
    try {
      const created = await createWorkflowDraft(id, { retryAfterCheck });
      setPending(readPendingDraftCreation());
      setFound(true);
      setNotice(`Empty draft created for ${created.workflowId}. Load this ID below to edit it.`);
    } catch (value) {
      failure(value, "create");
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    if (busy || blocked || !pending || pending === "unavailable") return;
    setBusy(true);
    setError(null);
    setNotice(null);
    setRetryAllowed(false);
    try {
      const found = await reconcileDraftCreation(pending);
      setPending(readPendingDraftCreation());
      setFound(true);
      setNotice(`Draft found for ${found.workflowId}. Load this ID below to inspect it.`);
    } catch (value) {
      failure(value, "check");
    } finally {
      setBusy(false);
    }
  }

  async function acknowledge() {
    if (busy || blocked || !found || !pending || pending === "unavailable") return;
    setBusy(true);
    setError(null);
    try {
      await acknowledgeDraftCreation(pending);
      setPending(null);
      setFound(false);
      setNotice(`ID ${pending} recorded. Load it below to edit the draft.`);
    } catch (value) {
      failure(value, "check");
    } finally {
      setBusy(false);
    }
  }

  return <section aria-labelledby="workflow-create-title" aria-busy={busy}>
    <h3 id="workflow-create-title">Create an empty draft</h3>
    <p>Generate or enter a lowercase UUID and record it before creating. Drafts without revisions are not listed.
      The draft starts empty and must be edited and validated; this does not run a workflow.</p>
    {!canGenerateId && <p role="note">Secure ID generation is unavailable. Enter a lowercase UUID manually.</p>}
    {blocked && <p role="status">Save or discard unsaved edits before working with another draft.</p>}
    <form className="workflow-draft-form" onSubmit={(event) => void create(event)}>
      <div className="schedule-create-field">
        <label htmlFor="workflow-create-id">New workflow ID</label>
        <input id="workflow-create-id" value={id} disabled={busy || blocked || pending !== null}
          onChange={(event) => { setId(event.target.value); setError(null); setNotice(null); }}
          placeholder="00000000-0000-0000-0000-000000000000" required />
      </div>
      <button className="button button--secondary" type="button"
        disabled={busy || blocked || pending !== null || !canGenerateId}
        onClick={() => {
          try {
            setId(crypto.randomUUID());
            setError(null);
            setNotice(null);
          } catch {
            setError("A secure workflow ID could not be generated. Enter a lowercase UUID manually.");
          }
        }}>Generate workflow ID</button>
      <button className="button button--secondary" type="submit"
        disabled={busy || blocked || pending === "unavailable" || (pending !== null && !retryAllowed)}>
        Create empty draft
      </button>
      {pending && pending !== "unavailable" && <button className="button button--secondary"
        type="button" disabled={busy || blocked} onClick={() => void check()}>Check draft creation</button>}
      {found && pending && pending !== "unavailable" && <button className="button button--secondary"
        type="button" disabled={busy || blocked} onClick={() => void acknowledge()}>I recorded this ID</button>}
    </form>
    {busy && <p role="status">Working with the draft...</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <div className="review-error" role="alert"><p>{error}</p></div>}
  </section>;
}

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
  const editorRef = useRef<HTMLTextAreaElement>(null);
  return <>
    <p>Workflow <code>{draft.workflowId}</code> · saved version <strong>{draft.version}</strong></p>
    <WorkflowNodeOrder document={document} disabled={busy || reloadRequired}
      onDocumentChange={onDocumentChange} />
    <label className="workflow-document-label" htmlFor="workflow-draft-document">Workflow draft JSON</label>
    <p id="workflow-draft-editor-help">Edit the JSON directly. Changes are local until saved. Choose a revision identifier before creating a revision.</p>
    {document === "" && <button className="button button--secondary" type="button"
      disabled={busy || reloadRequired} onClick={() => {
        onDocumentChange(JSON.stringify({ schemaVersion: 1, revision: "draft", nodes: [], edges: [] }, null, 2));
        editorRef.current?.focus();
      }}>Initialize empty draft</button>}
    <textarea id="workflow-draft-document" className="workflow-json workflow-json-editor"
      ref={editorRef}
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
    <WorkflowDraftCreation busy={busy} setBusy={setBusy} blocked={unsavedChanges} onDenied={(value) => {
      setDraft(null);
      setEditorDocument("");
      setValidation(null);
      setRevision(null);
      setId("");
      onDenied(value);
    }} />
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
