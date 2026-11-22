import { useEffect, useRef, useState } from "react";
import type { RevisionListOutput, RevisionOutput, WorkflowIdListOutput } from "../api/generated";
import { fetchRevision, fetchRevisionPage, fetchWorkflowPage, WorkflowDiscoveryError } from "../api/workflows";
import { WorkflowDraftError } from "../api/workflow-drafts";
import { WorkflowDraftPanel } from "./WorkflowDraftPanel";
import { WorkflowNodeCatalog } from "./WorkflowNodeCatalog";

type Request = { cursor: string | null; attempt: number };
const firstPage = (): Request => ({ cursor: null, attempt: 0 });

export function WorkflowDiscovery() {
  const [workflows, setWorkflows] = useState<WorkflowIdListOutput | null>(null);
  const [revisions, setRevisions] = useState<RevisionListOutput | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedRevision, setSelectedRevision] = useState<string | null>(null);
  const [detail, setDetail] = useState<RevisionOutput | null>(null);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [workflowRequest, setWorkflowRequest] = useState<Request>(firstPage);
  const [revisionRequest, setRevisionRequest] = useState<Request>(firstPage);
  const [workflowLoading, setWorkflowLoading] = useState(true);
  const [revisionLoading, setRevisionLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState<unknown>(null);
  const [revisionError, setRevisionError] = useState<unknown>(null);
  const workflowController = useRef<AbortController | null>(null);
  const revisionController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const workflowHeading = useRef<HTMLHeadingElement>(null);
  const revisionHeading = useRef<HTMLHeadingElement>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const content = useRef<HTMLElement>(null);
  const retryButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);

  function denied(error: unknown) {
    if (!(error instanceof WorkflowDiscoveryError || error instanceof WorkflowDraftError) ||
        (error.status !== 401 && error.status !== 403)) return false;
    restoreFocus.current = Boolean(content.current?.contains(document.activeElement));
    workflowController.current?.abort();
    revisionController.current?.abort();
    detailController.current?.abort();
    setWorkflows(null);
    setRevisions(null);
    setSelected(null);
    setSelectedRevision(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
    setWorkflowLoading(false);
    setRevisionLoading(false);
    setRevisionError(null);
    setWorkflowError(error);
    return true;
  }

  useEffect(() => {
    if (workflowError !== null && restoreFocus.current) {
      retryButton.current?.focus();
      restoreFocus.current = false;
    }
  }, [workflowError]);

  useEffect(() => {
    const controller = new AbortController();
    workflowController.current = controller;
    setWorkflowLoading(true);
    setWorkflowError(null);
    setWorkflows(null);
    void fetchWorkflowPage(workflowRequest.cursor, controller.signal).then((page) => {
      if (!controller.signal.aborted) setWorkflows(page);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted && !denied(error)) setWorkflowError(error);
    }).finally(() => {
      if (!controller.signal.aborted) setWorkflowLoading(false);
    });
    return () => controller.abort();
  }, [workflowRequest]);

  useEffect(() => {
    if (selected === null) return;
    const controller = new AbortController();
    revisionController.current = controller;
    setRevisionLoading(true);
    setRevisionError(null);
    setRevisions(null);
    void fetchRevisionPage(selected, revisionRequest.cursor, controller.signal).then((page) => {
      if (!controller.signal.aborted) setRevisions(page);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted && !denied(error)) setRevisionError(error);
    }).finally(() => {
      if (!controller.signal.aborted) setRevisionLoading(false);
    });
    return () => controller.abort();
  }, [selected, revisionRequest]);

  useEffect(() => {
    if (selected === null || selectedRevision === null) return;
    const controller = new AbortController();
    detailController.current = controller;
    setDetailLoading(true);
    setDetailError(null);
    setDetail(null);
    void fetchRevision(selected, selectedRevision, controller.signal).then((value) => {
      if (!controller.signal.aborted) setDetail(value);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted && !denied(error)) setDetailError(error);
    }).finally(() => {
      if (!controller.signal.aborted) setDetailLoading(false);
    });
    return () => controller.abort();
  }, [selected, selectedRevision, detailAttempt]);

  function clearDetail() {
    detailController.current?.abort();
    setSelectedRevision(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
  }

  function select(id: string) {
    revisionController.current?.abort();
    clearDetail();
    setRevisions(null);
    setRevisionError(null);
    setRevisionRequest(firstPage());
    setSelected(id);
  }

  function retryWorkflows() {
    const accessDenied = (workflowError instanceof WorkflowDiscoveryError || workflowError instanceof WorkflowDraftError) &&
      (workflowError.status === 401 || workflowError.status === 403);
    workflowHeading.current?.focus();
    setWorkflowRequest((current) => ({ cursor: accessDenied ? null : current.cursor, attempt: current.attempt + 1 }));
  }

  const errorText = (error: unknown) =>
    (error instanceof WorkflowDiscoveryError || error instanceof WorkflowDraftError) && (error.status === 401 || error.status === 403)
      ? "Access to saved workflows is unavailable. Sign in with an authorized account."
      : error instanceof Error ? error.message : "The workflow service could not be reached.";

  return (
    <section ref={content} className="review-queue" aria-labelledby="workflow-discovery-title">
      <header className="page-heading"><div className="page-title">
        <p className="eyebrow">SAVED WORKFLOWS</p>
        <h1 id="workflow-discovery-title" tabIndex={-1}>Workflows</h1>
        <p className="page-description">Browse saved workflow IDs and inspect immutable revisions.</p>
      </div></header>
      <p className="review-blocked-note" role="note">
        Browse immutable, read-only revisions or create, edit and validate a draft below. Workflow execution, scheduling, model readiness and publishing are not offered here.
      </p>
      {!(workflowError instanceof WorkflowDiscoveryError || workflowError instanceof WorkflowDraftError) ||
       (workflowError.status !== 401 && workflowError.status !== 403)
        ? <><WorkflowNodeCatalog onDenied={denied} /><WorkflowDraftPanel onDenied={(error) => { denied(error); }} /></> : null}
      <section aria-labelledby="workflow-list-title" aria-busy={workflowLoading}>
        <h2 ref={workflowHeading} id="workflow-list-title" tabIndex={-1}>Workflow IDs</h2>
        {workflowLoading && <p role="status">Loading workflows...</p>}
        {workflowError !== null && <div className="review-error" role="alert">
          <p>{errorText(workflowError)}</p>
          {(workflowError instanceof WorkflowDiscoveryError || workflowError instanceof WorkflowDraftError) && workflowError.status === 401 && <a className="review-login-link" href="/api/v1/auth/login">Sign in</a>}
          <button ref={retryButton} className="button button--secondary" type="button" onClick={retryWorkflows}>Retry</button>
        </div>}
        {workflows && workflows.data.length === 0 && <p role="status">No saved workflows are available.</p>}
        {workflows && workflows.data.length > 0 && <ul className="workflow-id-list">
          {workflows.data.map(({ workflowId }) => <li key={workflowId}>
            <button type="button" className="button button--secondary workflow-id-button" aria-pressed={selected === workflowId} onClick={() => select(workflowId)}>
              <code>{workflowId}</code>
            </button>
          </li>)}
        </ul>}
        {workflows?.nextCursor && <button className="button button--secondary" type="button" onClick={() => {
          revisionController.current?.abort(); clearDetail(); setSelected(null); setRevisions(null);
          workflowHeading.current?.focus();
          setWorkflowRequest({ cursor: workflows.nextCursor, attempt: 0 });
        }}>Next workflows</button>}
        {workflowRequest.cursor !== null && !workflowLoading && <button className="button button--secondary" type="button" onClick={() => {
          revisionController.current?.abort(); clearDetail(); setSelected(null); setRevisions(null); workflowHeading.current?.focus(); setWorkflowRequest(firstPage());
        }}>First workflows</button>}
      </section>
      {selected && <section className="workflow-revisions" aria-labelledby="workflow-revisions-title" aria-busy={revisionLoading}>
        <h2 ref={revisionHeading} id="workflow-revisions-title" tabIndex={-1}>Saved revisions</h2>
        <p>Workflow <code>{selected}</code></p>
        {revisionLoading && <p role="status">Loading revisions...</p>}
        {revisionError !== null && <div className="review-error" role="alert">
          <p>{errorText(revisionError)}</p>
          <button className="button button--secondary" type="button" onClick={() => { revisionHeading.current?.focus(); setRevisionRequest((current) => ({ ...current, attempt: current.attempt + 1 })); }}>Retry revisions</button>
        </div>}
        {revisions && revisions.data.length === 0 && <p role="status">No saved revisions are available for this workflow.</p>}
        {revisions && revisions.data.length > 0 && <ul className="review-list">
          {revisions.data.map((item) => <li className="review-card" key={item.revision}>
            <dl className="review-metadata">
              <div><dt>Revision</dt><dd><code>{item.revision}</code></dd></div>
              <div><dt>Created</dt><dd><time dateTime={item.createdAt}>{item.createdAt}</time></dd></div>
            </dl>
            <button type="button" className="button button--secondary workflow-inspect-button" aria-pressed={selectedRevision === item.revision}
              onClick={() => {
                detailController.current?.abort();
                setDetail(null);
                setDetailError(null);
                setDetailLoading(true);
                setSelectedRevision(item.revision);
                setDetailAttempt((current) => current + 1);
              }}>Inspect <span className="workflow-revision-label">{item.revision}</span></button>
          </li>)}
        </ul>}
        {revisions?.nextCursor && <button className="button button--secondary" type="button" onClick={() => { clearDetail(); revisionHeading.current?.focus(); setRevisionRequest({ cursor: revisions.nextCursor, attempt: 0 }); }}>Next revisions</button>}
        {revisionRequest.cursor !== null && !revisionLoading && <button className="button button--secondary" type="button" onClick={() => { clearDetail(); revisionHeading.current?.focus(); setRevisionRequest(firstPage()); }}>First revisions</button>}
        <section className="workflow-inspector" aria-labelledby="workflow-inspector-title" aria-busy={detailLoading}>
          <h3 ref={detailHeading} id="workflow-inspector-title" tabIndex={-1}>Revision inspector</h3>
          {selectedRevision === null && <p>Select a saved revision to inspect its exact canonical JSON and returned SHA-256.</p>}
          {selectedRevision !== null && <p>Selected revision: <code className="workflow-revision-label">{selectedRevision}</code></p>}
          {detailLoading && <p role="status">Loading saved revision...</p>}
          {detailError !== null && <div className="review-error" role="alert">
            <p>{errorText(detailError)}</p>
            <button type="button" className="button button--secondary" onClick={() => { detailHeading.current?.focus(); setDetailAttempt((current) => current + 1); }}>Retry revision</button>
          </div>}
          {detail && <>
            <p role="status">Saved revision loaded.</p>
            <h4>Returned SHA-256</h4>
            <code className="workflow-digest">{detail.sha256}</code>
            <h4>Exact canonical JSON</h4>
            <pre className="workflow-json" tabIndex={0} aria-label="Exact canonical JSON"><code>{detail.canonicalJson}</code></pre>
          </>}
        </section>
      </section>}
    </section>
  );
}
