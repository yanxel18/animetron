import { useEffect, useRef, useState } from "react";

import type { DescriptorOutput } from "../api/generated";
import {
  fetchSchedulePage,
  ScheduleListError,
  scheduleErrorMessage,
  setScheduleEnabled,
} from "../api/schedules";
import { SchedulePreview } from "./SchedulePreview";

function formatUtc(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value)) + " UTC";
}

export function ScheduleList() {
  const [schedules, setSchedules] = useState<DescriptorOutput[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [request, setRequest] = useState<{ cursor: string | null; attempt: number }>({
    cursor: null,
    attempt: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const activeUpdate = useRef<AbortController | null>(null);
  const scheduleList = useRef<HTMLUListElement | null>(null);
  const recoveryButton = useRef<HTMLButtonElement | null>(null);
  const focusRecovery = useRef(false);
  const [updating, setUpdating] = useState(false);
  const [updateFailed, setUpdateFailed] = useState(false);
  const [updateStatus, setUpdateStatus] = useState("");

  useEffect(() => () => activeUpdate.current?.abort(), []);
  useEffect(() => {
    if (updateFailed && error !== null && focusRecovery.current) {
      recoveryButton.current?.focus();
      focusRecovery.current = false;
    }
  }, [updateFailed, error]);

  useEffect(() => {
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError(null);
    if (request.cursor === null) {
      setSchedules([]);
      setNextCursor(null);
    }

    void fetchSchedulePage(request.cursor, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        setSchedules((current) =>
          request.cursor === null ? page.data : [...current, ...page.data],
        );
        setNextCursor(page.nextCursor);
      })
      .catch((requestError: unknown) => {
        if (controller.signal.aborted) return;
        if (
          requestError instanceof ScheduleListError &&
          (requestError.status === 401 || requestError.status === 403)
        ) {
          setSchedules([]);
          setNextCursor(null);
        }
        setError(requestError);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [request]);

  const denied = error instanceof ScheduleListError &&
    (error.status === 401 || error.status === 403);

  function retry() {
    setRequest((current) => ({
      cursor: denied || updateFailed ? null : current.cursor,
      attempt: current.attempt + 1,
    }));
    setUpdateFailed(false);
  }

  function accessDenied(requestError: ScheduleListError) {
    activeRequest.current?.abort();
    if (activeUpdate.current) {
      focusRecovery.current = document.activeElement === document.body ||
        Boolean(scheduleList.current?.contains(document.activeElement));
      setUpdateFailed(true);
    }
    activeUpdate.current?.abort();
    activeUpdate.current = null;
    setUpdating(false);
    setUpdateStatus("");
    setLoading(false);
    setSchedules([]);
    setNextCursor(null);
    setError(requestError);
  }

  async function toggle(schedule: DescriptorOutput) {
    if (activeUpdate.current || loading) return;
    const controller = new AbortController();
    activeUpdate.current = controller;
    setUpdating(true);
    setUpdateStatus("Updating schedule...");
    try {
      const updated = await setScheduleEnabled(schedule, !schedule.enabled, controller.signal);
      if (!controller.signal.aborted) {
        setSchedules((current) => current.map((item) => item.id === updated.id ? updated : item));
        setUpdateStatus(`Schedule ${updated.id} ${updated.enabled ? "resumed" : "paused"}.`);
      }
    } catch (requestError) {
      if (controller.signal.aborted) return;
      activeRequest.current?.abort();
      focusRecovery.current = document.activeElement === document.body ||
        Boolean(scheduleList.current?.contains(document.activeElement));
      setSchedules([]);
      setNextCursor(null);
      setUpdateFailed(true);
      setUpdateStatus("");
      setError(requestError);
    } finally {
      if (!controller.signal.aborted) {
        activeUpdate.current = null;
        setUpdating(false);
      }
    }
  }

  return (
    <section id="schedules" className="review-queue" aria-labelledby="schedule-list-title" aria-busy={loading}>
      <header className="page-heading">
        <div className="page-title">
          <p className="eyebrow">SCHEDULE DESCRIPTORS</p>
          <h1 id="schedule-list-title" tabIndex={-1}>Schedules</h1>
          <p className="page-description">
            Inspect saved schedules and their immutable workflow revisions.
          </p>
        </div>
      </header>
      <p className="review-blocked-note" role="note">
        Scheduler dispatch is not implemented. Saved settings do not guarantee
        that a run will start. Creating and editing schedule details are unavailable here.
      </p>
      <p className="visually-hidden" role="status">{updateStatus}</p>
      {loading && <p role="status">Loading saved schedules...</p>}
      {error !== null && (
        <div className="review-error" role="alert">
          <p>
            {scheduleErrorMessage(error)}
            {updateFailed && " The update may not have completed. Refresh schedules before trying again."}
          </p>
          {error instanceof ScheduleListError && error.status === 401 && (
            <a className="review-login-link" href="/api/v1/auth/login">Sign in</a>
          )}
          <button ref={recoveryButton} className="button button--secondary" type="button" onClick={retry}>
            {updateFailed ? "Refresh schedules" : "Retry"}
          </button>
        </div>
      )}
      {!loading && error === null && schedules.length === 0 && (
        <p role="status">No saved schedules are available.</p>
      )}
      {schedules.length > 0 && (
        <ul ref={scheduleList} className="review-list">
          {schedules.map((schedule) => (
            <li className="review-list-item" key={schedule.id}>
              <article className="review-card" aria-labelledby={`schedule-${schedule.id}`}>
                <header className="review-card-heading">
                  <div className="review-card-title">
                    <p className="panel-kicker">SAVED SCHEDULE</p>
                    <h2 id={`schedule-${schedule.id}`}><code>{schedule.id}</code></h2>
                  </div>
                  <span className="review-state">{schedule.enabled ? "Enabled" : "Paused"}</span>
                </header>
                <dl className="review-metadata">
                  <div><dt>Workflow</dt><dd><code>{schedule.workflowId}</code></dd></div>
                  <div><dt>Revision</dt><dd><code>{schedule.revision}</code></dd></div>
                  <div><dt>Cron expression</dt><dd><code>{schedule.expression}</code></dd></div>
                  <div><dt>Time zone</dt><dd>{schedule.timeZone}</dd></div>
                  <div>
                    <dt>Next due time</dt>
                    <dd>
                      {schedule.nextDueAt === null
                        ? "Not scheduled"
                        : <time dateTime={schedule.nextDueAt}>{formatUtc(schedule.nextDueAt)}</time>}
                    </dd>
                  </div>
                  <div><dt>Overlap and missed runs</dt><dd>Skip</dd></div>
                </dl>
                <div className="schedule-actions">
                  <button
                    className="button button--secondary"
                    type="button"
                    aria-label={`${schedule.enabled ? "Pause" : "Resume"} schedule ${schedule.id}`}
                    disabled={loading || updating}
                    onClick={() => void toggle(schedule)}
                  >
                    {schedule.enabled ? "Pause" : "Resume"}
                  </button>
                  <SchedulePreview key={schedule.version} id={schedule.id} onAccessDenied={accessDenied} />
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}
      {nextCursor !== null && error === null && (
        <div className="review-pagination">
          <button
            className="button button--secondary"
            type="button"
            disabled={loading || updating}
            onClick={() => setRequest((current) => ({ cursor: nextCursor, attempt: current.attempt + 1 }))}
          >
            {loading ? "Loading..." : "Load more"}
          </button>
        </div>
      )}
    </section>
  );
}
