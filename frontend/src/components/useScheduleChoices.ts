import { useEffect, useRef, useState } from "react";

import type { RevisionSummaryOutput } from "../api/generated";
import { ScheduleListError } from "../api/schedules";
import { fetchRevisionPage, fetchWorkflowPage, WorkflowDiscoveryError } from "../api/workflows";

function accessError(error: unknown): ScheduleListError | null {
  if (!(error instanceof WorkflowDiscoveryError) ||
      (error.status !== 401 && error.status !== 403)) return null;
  return new ScheduleListError(
    error.status === 401
      ? "Sign in with an owner account to create schedules."
      : "Owner access is required to create schedules.",
    error.status,
  );
}

export function useScheduleChoices(onAuthorizationLost: (error: ScheduleListError) => void) {
  const [workflowIds, setWorkflowIds] = useState<string[]>([]);
  const [workflowCursor, setWorkflowCursor] = useState<string | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(true);
  const [workflowError, setWorkflowError] = useState<unknown>(null);
  const [workflowAttempt, setWorkflowAttempt] = useState(0);
  const [selectedWorkflow, setSelectedWorkflow] = useState("");
  const [revisions, setRevisions] = useState<RevisionSummaryOutput[]>([]);
  const [revisionCursor, setRevisionCursor] = useState<string | null>(null);
  const [revisionLoading, setRevisionLoading] = useState(false);
  const [revisionError, setRevisionError] = useState<unknown>(null);
  const [selectedRevision, setSelectedRevision] = useState("");
  const [denied, setDenied] = useState(false);
  const [accessMessage, setAccessMessage] = useState("");
  const workflowController = useRef<AbortController | null>(null);
  const revisionController = useRef<AbortController | null>(null);
  const onAuthorizationLostRef = useRef(onAuthorizationLost);
  onAuthorizationLostRef.current = onAuthorizationLost;

  useEffect(() => () => {
    workflowController.current?.abort();
    revisionController.current?.abort();
  }, []);

  function clearForAccess(error: ScheduleListError) {
    workflowController.current?.abort();
    revisionController.current?.abort();
    setDenied(true);
    setAccessMessage(error.message);
    setWorkflowIds([]);
    setWorkflowCursor(null);
    setWorkflowError(null);
    setWorkflowLoading(false);
    setSelectedWorkflow("");
    setRevisions([]);
    setRevisionCursor(null);
    setRevisionError(null);
    setRevisionLoading(false);
    setSelectedRevision("");
    onAuthorizationLostRef.current(error);
  }

  useEffect(() => {
    const controller = new AbortController();
    workflowController.current = controller;
    setWorkflowLoading(true);
    setWorkflowError(null);
    void fetchWorkflowPage(null, controller.signal).then((page) => {
      if (controller.signal.aborted) return;
      setWorkflowIds(page.data.map((item) => item.workflowId));
      setWorkflowCursor(page.nextCursor);
      setDenied(false);
      setAccessMessage("");
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setWorkflowError(error);
      const access = accessError(error);
      if (access) clearForAccess(access);
    }).finally(() => {
      if (!controller.signal.aborted) {
        if (workflowController.current === controller) workflowController.current = null;
        setWorkflowLoading(false);
      }
    });
    return () => controller.abort();
  }, [workflowAttempt]);

  useEffect(() => {
    if (!selectedWorkflow || denied) {
      setRevisions([]);
      setRevisionCursor(null);
      setSelectedRevision("");
      setRevisionError(null);
      setRevisionLoading(false);
      return;
    }
    const controller = new AbortController();
    revisionController.current = controller;
    setRevisions([]);
    setRevisionCursor(null);
    setSelectedRevision("");
    setRevisionError(null);
    setRevisionLoading(true);
    void fetchRevisionPage(selectedWorkflow, null, controller.signal).then((page) => {
      if (controller.signal.aborted) return;
      setRevisions(page.data);
      setRevisionCursor(page.nextCursor);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setRevisionError(error);
      const access = accessError(error);
      if (access) clearForAccess(access);
    }).finally(() => {
      if (!controller.signal.aborted) {
        if (revisionController.current === controller) revisionController.current = null;
        setRevisionLoading(false);
      }
    });
    return () => controller.abort();
  }, [selectedWorkflow, denied]);

  function selectWorkflow(value: string) {
    revisionController.current?.abort();
    setSelectedWorkflow(value);
    setSelectedRevision("");
    setRevisions([]);
    setRevisionCursor(null);
    setRevisionError(null);
  }

  async function loadMoreWorkflows() {
    if (!workflowCursor || workflowController.current) return;
    const controller = new AbortController();
    workflowController.current = controller;
    setWorkflowLoading(true);
    setWorkflowError(null);
    try {
      const page = await fetchWorkflowPage(workflowCursor, controller.signal);
      if (!controller.signal.aborted) {
        setWorkflowIds((current) => [...current, ...page.data.map((item) => item.workflowId)]);
        setWorkflowCursor(page.nextCursor);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setWorkflowError(error);
        const access = accessError(error);
        if (access) clearForAccess(access);
      }
    } finally {
      if (!controller.signal.aborted) {
        workflowController.current = null;
        setWorkflowLoading(false);
      }
    }
  }

  async function loadMoreRevisions() {
    if (!selectedWorkflow || !revisionCursor || revisionController.current) return;
    const workflowId = selectedWorkflow;
    const controller = new AbortController();
    revisionController.current = controller;
    setRevisionLoading(true);
    setRevisionError(null);
    try {
      const page = await fetchRevisionPage(workflowId, revisionCursor, controller.signal);
      if (!controller.signal.aborted && selectedWorkflow === workflowId) {
        setRevisions((current) => [...current, ...page.data]);
        setRevisionCursor(page.nextCursor);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setRevisionError(error);
        const access = accessError(error);
        if (access) clearForAccess(access);
      }
    } finally {
      if (!controller.signal.aborted) {
        revisionController.current = null;
        setRevisionLoading(false);
      }
    }
  }

  function retryWorkflows() {
    if (workflowError !== null) setWorkflowAttempt((current) => current + 1);
  }

  return {
    workflowIds,
    workflowCursor,
    workflowLoading,
    workflowError,
    retryWorkflows,
    loadMoreWorkflows,
    selectedWorkflow,
    selectWorkflow,
    revisions,
    revisionCursor,
    revisionLoading,
    revisionError,
    loadMoreRevisions,
    selectedRevision,
    setSelectedRevision,
    denied,
    accessMessage,
    clearForAccess,
  };
}
