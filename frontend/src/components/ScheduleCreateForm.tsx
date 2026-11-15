import { useEffect, useRef, useState, type FormEvent } from "react";

import type { DescriptorInput, DescriptorOutput } from "../api/generated";
import {
  createScheduleDescriptor,
  readScheduleCreateIntent,
  SCHEDULE_CREATE_PENDING_KEY,
  ScheduleCreateError,
  type ScheduleCreateIntent,
} from "../api/schedule-create";
import { ScheduleListError } from "../api/schedules";
import { WorkflowDiscoveryError } from "../api/workflows";
import { useScheduleChoices } from "./useScheduleChoices";

type Props = {
  onCreated: (schedule: DescriptorOutput) => void;
  onAuthorizationLost: (error: ScheduleListError) => void;
  onRefresh: () => void;
};

type FieldErrors = Partial<Record<"workflowId" | "revision" | "expression" | "timeZone", string>>;

function points(value: string) {
  return Array.from(value).length;
}

function message(error: unknown): string {
  if (error instanceof ScheduleCreateError || error instanceof WorkflowDiscoveryError) {
    return error.message;
  }
  return "The schedule service could not be reached.";
}

function accessError(error: unknown): ScheduleListError | null {
  if (error instanceof ScheduleCreateError &&
      (error.status === 401 || error.status === 403)) {
    return new ScheduleListError(
      error.status === 401
        ? "Sign in with an owner account to create schedules."
        : "Owner access is required to create schedules.",
      error.status,
    );
  }
  return null;
}

function validate(
  workflowId: string,
  workflowIds: string[],
  revision: string,
  revisions: Array<{ revision: string }>,
  expression: string,
  timeZone: string,
): FieldErrors {
  const errors: FieldErrors = {};
  if (!workflowIds.includes(workflowId)) errors.workflowId = "Choose a persisted workflow ID.";
  if (!revisions.some((item) => item.revision === revision)) {
    errors.revision = "Choose a saved revision for the selected workflow.";
  }
  if (points(expression) < 1 || points(expression) > 256) {
    errors.expression = "Enter a five-field cron expression between 1 and 256 characters.";
  }
  if (points(timeZone) < 1 || points(timeZone) > 255) {
    errors.timeZone = "Enter an IANA time zone between 1 and 255 characters.";
  }
  return errors;
}

export function ScheduleCreateForm({ onCreated, onAuthorizationLost, onRefresh }: Props) {
  const choices = useScheduleChoices(onAuthorizationLost);
  const [expression, setExpression] = useState("");
  const [timeZone, setTimeZone] = useState("UTC");
  const [enabled, setEnabled] = useState(false);
  const [intent, setIntent] = useState<ScheduleCreateIntent>(readScheduleCreateIntent);
  const [acknowledged, setAcknowledged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState("");
  const [submitErrorTitle, setSubmitErrorTitle] = useState("Schedule was not created");
  const [errorAttempt, setErrorAttempt] = useState(0);
  const [success, setSuccess] = useState("");
  const submitInFlight = useRef(false);
  const mounted = useRef(true);
  const summary = useRef<HTMLDivElement>(null);

  useEffect(() => {
    mounted.current = true;
    const storageChanged = (event: StorageEvent) => {
      if (event.key === SCHEDULE_CREATE_PENDING_KEY && event.newValue !== null) {
        setIntent("pending");
        setAcknowledged(false);
      }
    };
    window.addEventListener("storage", storageChanged);
    return () => {
      mounted.current = false;
      window.removeEventListener("storage", storageChanged);
    };
  }, []);

  useEffect(() => {
    if (submitError) summary.current?.focus();
  }, [submitError, errorAttempt]);

  function clearProtectedState(error: ScheduleListError) {
    choices.clearForAccess(error);
    setExpression("");
    setTimeZone("UTC");
    setEnabled(false);
    setAcknowledged(false);
    setFieldErrors({});
    setSuccess("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitInFlight.current || choices.denied) return;
    setSubmitError("");
    setSuccess("");
    const errors = validate(
      choices.selectedWorkflow,
      choices.workflowIds,
      choices.selectedRevision,
      choices.revisions,
      expression,
      timeZone,
    );
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      setSubmitErrorTitle("Correct the schedule details");
      setSubmitError("Review the highlighted fields before creating a schedule.");
      setErrorAttempt((current) => current + 1);
      return;
    }

    const priorUncertainAttempt = intent === "pending";
    const input: DescriptorInput = {
      workflowId: choices.selectedWorkflow,
      revision: choices.selectedRevision,
      expression,
      timeZone,
      enabled,
      overlapPolicy: "skip",
      missedRunPolicy: "skip",
    };
    submitInFlight.current = true;
    setSubmitting(true);
    setAcknowledged(false);
    try {
      const created = await createScheduleDescriptor(input, {
        acknowledgeUncertain: acknowledged,
      });
      if (!mounted.current) return;
      setIntent(readScheduleCreateIntent());
      choices.selectWorkflow("");
      choices.setSelectedRevision("");
      setExpression("");
      setTimeZone("UTC");
      setEnabled(false);
      setFieldErrors({});
      setSuccess(priorUncertainAttempt
        ? `This attempt returned a verified descriptor (${created.id}), but the earlier uncertain attempt remains unresolved. Duplicates are possible. Scheduler dispatch is not implemented, so saved schedules will not run automatically.`
        : `Schedule descriptor ${created.id} was saved. Scheduler dispatch is not implemented, so it will not run automatically.`);
      onCreated(created);
    } catch (error) {
      if (!mounted.current) return;
      setSubmitErrorTitle(error instanceof ScheduleCreateError && error.uncertain
        ? "Schedule outcome uncertain"
        : "Schedule was not created");
      setSubmitError(message(error));
      setErrorAttempt((current) => current + 1);
      setIntent(readScheduleCreateIntent());
      const access = accessError(error);
      if (access) {
        clearProtectedState(access);
      }
      if (error instanceof ScheduleCreateError &&
          (error.uncertain || error.requiresAcknowledgement)) {
        setAcknowledged(false);
      }
    } finally {
      submitInFlight.current = false;
      if (mounted.current) setSubmitting(false);
    }
  }

  const lockSupported = typeof navigator.locks?.request === "function";
  const creationAvailable = intent !== "unavailable" && lockSupported;
  const visible = !choices.denied && choices.workflowIds.length > 0;

  return (
    <section id="schedule-create-form" className="schedule-create" aria-labelledby="schedule-create-title" aria-busy={choices.workflowLoading || submitting}>
      <header className="schedule-create-heading">
        <div>
          <p className="panel-kicker">OWNER ACTION</p>
          <h2 id="schedule-create-title">Create a schedule descriptor</h2>
        </div>
      </header>
      <p className="schedule-create-policy" role="note">
        Saves settings only. Scheduler dispatch is not implemented, so saved schedules will not run automatically.
        Overlap and missed-run policies are fixed to <code>skip</code>; a schedule never grants publication approval.
      </p>
      {intent === "unavailable" && (
        <p className="review-error" role="alert">
          Safe creation is unavailable because this browser cannot read the durable pending-attempt marker.
        </p>
      )}
      {!lockSupported && (
        <p className="review-error" role="alert">
          Safe creation is unavailable because this browser cannot coordinate attempts across tabs.
        </p>
      )}
      {intent === "pending" && !choices.denied && (
        <div className="schedule-create-uncertain" role="alert">
          <p>
            A previous creation may have succeeded. A refreshed list, including a matching descriptor, cannot prove
            that it came from that attempt. Starting another attempt could create a duplicate.
          </p>
          <button className="button button--secondary" type="button" onClick={onRefresh}>
            Refresh schedules
          </button>
          <label className="schedule-create-acknowledge">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.currentTarget.checked)}
            />
            I understand the prior attempt may have succeeded and a duplicate is possible; allow me to start a new attempt.
          </label>
        </div>
      )}
      {choices.accessMessage && (
        <div className="review-error" role="alert">
          <p>{choices.accessMessage} Protected workflow and schedule data were cleared.</p>
        </div>
      )}
      {choices.workflowLoading && <p role="status">Checking owner access and loading saved workflow IDs...</p>}
      {choices.workflowError !== null && !choices.denied && (
        <div className="review-error" role="alert">
          <p>{message(choices.workflowError)}</p>
          <button className="button button--secondary" type="button" onClick={choices.retryWorkflows}>
            Retry workflow discovery
          </button>
        </div>
      )}
      {!choices.workflowLoading && !choices.workflowError && !choices.denied && choices.workflowIds.length === 0 && (
        <p role="status">No persisted workflows are available to schedule.</p>
      )}
      {visible && (
        <form className="schedule-create-form" noValidate onSubmit={(event) => void submit(event)}>
          {submitError && (
            <div ref={summary} className="review-error schedule-create-summary" role="alert" tabIndex={-1} aria-labelledby="schedule-create-error-title">
              <div>
                <h3 id="schedule-create-error-title">{submitErrorTitle}</h3>
                <p>{submitError}</p>
                {Object.entries(fieldErrors).length > 0 && (
                  <ul>
                    {Object.entries(fieldErrors).map(([field, error]) => (
                      <li key={field}><a href={`#schedule-${field}`}>{error}</a></li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
          {success && <p className="schedule-create-success" role="status">{success}</p>}
          <div className="schedule-create-grid">
            <div className="schedule-create-field">
              <label htmlFor="schedule-workflowId">Workflow ID</label>
              <select id="schedule-workflowId" value={choices.selectedWorkflow} disabled={submitting} aria-describedby={fieldErrors.workflowId ? "schedule-workflowId-error" : undefined}
                onChange={(event) => {
                  choices.selectWorkflow(event.currentTarget.value);
                  setSubmitError("");
                  setFieldErrors((current) => ({ ...current, workflowId: undefined, revision: undefined }));
                }}>
                <option value="">Choose a saved workflow</option>
                {choices.workflowIds.map((id) => <option key={id} value={id}>{id}</option>)}
              </select>
              {fieldErrors.workflowId && <p id="schedule-workflowId-error" className="schedule-create-field-error">{fieldErrors.workflowId}</p>}
              {choices.workflowCursor && <button className="button button--secondary" type="button" disabled={choices.workflowLoading} onClick={() => void choices.loadMoreWorkflows()}>{choices.workflowLoading ? "Loading..." : "Load more workflows"}</button>}
            </div>
            <div className="schedule-create-field">
              <label htmlFor="schedule-revision">Saved revision</label>
              <select id="schedule-revision" value={choices.selectedRevision} disabled={!choices.selectedWorkflow || choices.revisionLoading || submitting} aria-describedby={fieldErrors.revision ? "schedule-revision-error" : undefined}
                onChange={(event) => {
                  choices.setSelectedRevision(event.currentTarget.value);
                  setSubmitError("");
                  setFieldErrors((current) => ({ ...current, revision: undefined }));
                }}>
                <option value="">Choose a saved revision</option>
                {choices.revisions.map(({ revision: item }) => <option key={item} value={item}>{item}</option>)}
              </select>
              {choices.revisionLoading && <p role="status">Loading saved revisions...</p>}
              {choices.revisionError !== null && <p className="schedule-create-field-error" role="alert">{message(choices.revisionError)}</p>}
              {fieldErrors.revision && <p id="schedule-revision-error" className="schedule-create-field-error">{fieldErrors.revision}</p>}
              {choices.revisionCursor && <button className="button button--secondary" type="button" disabled={choices.revisionLoading} onClick={() => void choices.loadMoreRevisions()}>{choices.revisionLoading ? "Loading..." : "Load more revisions"}</button>}
            </div>
            <div className="schedule-create-field">
              <label htmlFor="schedule-expression">Five-field cron expression</label>
              <input id="schedule-expression" value={expression} autoComplete="off" disabled={submitting} aria-describedby={fieldErrors.expression ? "schedule-expression-error" : "schedule-expression-hint"}
                onChange={(event) => { setExpression(event.currentTarget.value); setFieldErrors((current) => ({ ...current, expression: undefined })); }} />
              <p id="schedule-expression-hint" className="schedule-create-hint">Minute hour day-of-month month weekday. The server validates cron syntax.</p>
              {fieldErrors.expression && <p id="schedule-expression-error" className="schedule-create-field-error">{fieldErrors.expression}</p>}
            </div>
            <div className="schedule-create-field">
              <label htmlFor="schedule-timeZone">IANA time zone</label>
              <input id="schedule-timeZone" value={timeZone} autoComplete="off" disabled={submitting} aria-describedby={fieldErrors.timeZone ? "schedule-timeZone-error" : undefined}
                onChange={(event) => { setTimeZone(event.currentTarget.value); setFieldErrors((current) => ({ ...current, timeZone: undefined })); }} />
              {fieldErrors.timeZone && <p id="schedule-timeZone-error" className="schedule-create-field-error">{fieldErrors.timeZone}</p>}
            </div>
          </div>
          <label className="schedule-create-enabled">
            <input type="checkbox" checked={enabled} disabled={submitting} onChange={(event) => setEnabled(event.currentTarget.checked)} />
            Enable descriptor on save (no run will start; dispatch is not implemented)
          </label>
          <div className="schedule-create-actions">
            <button className="button button--primary" type="submit"
              disabled={submitting || !creationAvailable || (intent === "pending" && !acknowledged)}>
              {submitting ? "Saving descriptor..." : intent === "pending" ? "Start a new attempt" : "Create schedule"}
            </button>
          </div>
          <p className="schedule-create-hint">
            Creation is non-idempotent. After an uncertain response, this form will remain blocked until you explicitly acknowledge the duplicate risk and start a new attempt.
          </p>
        </form>
      )}
    </section>
  );
}
