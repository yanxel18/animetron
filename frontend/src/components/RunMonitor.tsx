import { useEffect, useRef, useState } from "react";

import type { RunEventOutput, RunState, RunStatusOutput } from "../api/generated";
import {
  fetchRunEvents,
  fetchRunStatus,
  RunMonitorError,
  runMonitorErrorMessage,
} from "../api/runs";
import { RunEventTimeline } from "./RunEventTimeline";

const pollDelayMs = 5_000;
const maximumPagesPerUpdate = 5;
const maximumVisibleEvents = 500;
const terminalStates: ReadonlySet<RunState> = new Set([
  "SUCCEEDED",
  "PARTIAL_FAILURE",
  "FAILED",
  "CANCELLED",
]);
const stateLabels: Record<RunState, string> = {
  QUEUED: "Queued",
  RUNNING: "Running",
  WAITING_REVIEW: "Waiting for review",
  SUCCEEDED: "Succeeded",
  PARTIAL_FAILURE: "Partially failed",
  FAILED: "Failed",
  CANCELLING: "Cancelling",
  CANCELLED: "Cancelled",
};

function formatTimestamp(value: Date) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value);
}

function isTerminal(state: RunState) {
  return terminalStates.has(state);
}

function statusAnnouncement(
  status: RunStatusOutput,
  newEventCount: number,
): string {
  const eventUpdate =
    newEventCount === 0
      ? "No new saved events."
      : `${newEventCount} new saved ${
          newEventCount === 1 ? "event" : "events"
        }.`;
  return `Run is ${stateLabels[status.state]}. ${eventUpdate}`;
}

export function RunMonitor() {
  const [runIdInput, setRunIdInput] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [status, setStatus] = useState<RunStatusOutput | null>(null);
  const [events, setEvents] = useState<RunEventOutput[]>([]);
  const [hasOlderEvents, setHasOlderEvents] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [connectionState, setConnectionState] = useState<
    "idle" | "connecting" | "live" | "retrying" | "complete"
  >("idle");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const cursorRef = useRef(0);
  const eventsRef = useRef<RunEventOutput[]>([]);
  const previousRunIdRef = useRef<string | null>(null);
  const previousStateRef = useRef<RunState | null>(null);

  useEffect(() => {
    if (runId === null) return;

    const controller = new AbortController();
    let timer: number | undefined;
    if (previousRunIdRef.current !== runId) {
      previousRunIdRef.current = runId;
      previousStateRef.current = null;
      cursorRef.current = 0;
      eventsRef.current = [];
      setEvents([]);
      setStatus(null);
      setError(null);
      setLastUpdated(null);
      setHasOlderEvents(false);
      setAnnouncement("");
      setIsLoading(true);
      setConnectionState("connecting");
    }

    const poll = async () => {
      try {
        const latestStatus = await fetchRunStatus(runId, controller.signal);
        if (controller.signal.aborted) return;

        const newEvents: RunEventOutput[] = [];
        let nextCursor = cursorRef.current;
        let hasMore = false;
        for (let pageNumber = 0; pageNumber < maximumPagesPerUpdate; pageNumber += 1) {
          const page = await fetchRunEvents(
            runId,
            nextCursor,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          newEvents.push(...page.data);
          nextCursor = page.nextAfterSequence;
          hasMore = page.hasMore;
          if (!page.hasMore) break;
        }

        cursorRef.current = nextCursor;
        setStatus(latestStatus);
        const combinedEvents = [...eventsRef.current, ...newEvents];
        if (combinedEvents.length > maximumVisibleEvents) {
          eventsRef.current = combinedEvents.slice(-maximumVisibleEvents);
          setHasOlderEvents(true);
        } else {
          eventsRef.current = combinedEvents;
        }
        setEvents(eventsRef.current);
        setLastUpdated(new Date());
        setError(null);

        if (
          previousStateRef.current !== latestStatus.state ||
          newEvents.length > 0
        ) {
          setAnnouncement(statusAnnouncement(latestStatus, newEvents.length));
        }
        previousStateRef.current = latestStatus.state;

        const caughtUp =
          !hasMore && latestStatus.lastSequence <= cursorRef.current;
        const complete = isTerminal(latestStatus.state) && caughtUp;
        setConnectionState(complete ? "complete" : "live");
        if (!complete) {
          timer = window.setTimeout(() => void poll(), pollDelayMs);
        }
      } catch (requestError: unknown) {
        if (controller.signal.aborted) return;
        setError(requestError);
        setConnectionState("retrying");
        timer = window.setTimeout(() => void poll(), pollDelayMs);
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    };

    void poll();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId, refreshToken]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextRunId = runIdInput.trim().toLowerCase();
    if (nextRunId === runId) {
      setRefreshToken((token) => token + 1);
      return;
    }
    setRunId(nextRunId);
  }

  const errorStatus = error instanceof RunMonitorError ? error.status : null;
  const connectionLabel = {
    idle: "Waiting for a run ID",
    connecting: "Connecting",
    live: "Live · checking every 5 seconds",
    retrying: "Connection interrupted · retrying",
    complete: "Run finished",
  }[connectionState];

  return (
    <section
      id="runs"
      className="run-monitor"
      aria-labelledby="run-monitor-title"
      aria-busy={isLoading}
      tabIndex={-1}
    >
      <header className="page-heading">
        <div className="page-title">
          <p className="eyebrow">EXECUTION HISTORY</p>
          <h1 id="run-monitor-title">Run monitor</h1>
          <p className="page-description">
            Inspect persisted status and ordered events for an existing workflow
            run.
          </p>
        </div>
        {runId !== null && (
          <div className="workflow-actions" aria-label="Run monitor actions">
            <button
              className="button button--secondary"
              type="button"
              disabled={isLoading}
              onClick={() => setRefreshToken((token) => token + 1)}
            >
              Refresh now
            </button>
          </div>
        )}
      </header>

      <form
        className="run-search-form"
        aria-label="Open a persisted run"
        onSubmit={handleSubmit}
      >
        <div className="run-id-field">
          <label htmlFor="run-id">Run ID</label>
          <input
            id="run-id"
            autoComplete="off"
            required
            pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
            title="Enter a valid version-4 UUID run ID."
            value={runIdInput}
            onChange={(event) => setRunIdInput(event.target.value)}
            aria-describedby="run-id-help"
          />
          <p id="run-id-help" className="run-field-help">
            Use the UUID from an existing run receipt.
          </p>
        </div>
        <button className="button button--primary" type="submit">
          Open run
        </button>
      </form>

      <p className="run-monitor-guidance" role="note">
        This monitor reads persisted run state only. It cannot start or cancel a
        run and does not invent progress.
      </p>

      {runId === null ? (
        <div className="run-monitor-empty">
          <p className="panel-kicker">NO RUN SELECTED</p>
          <h2>Enter a run ID to begin</h2>
          <p>
            Run history appears after you provide an ID for a persisted run.
          </p>
        </div>
      ) : (
        <section
          className="run-record panel"
          aria-labelledby="run-record-title"
          aria-busy={isLoading}
        >
          <header className="panel-heading">
            <div className="run-record-title">
              <p className="panel-kicker">PERSISTED RUN</p>
              <h2 id="run-record-title">
                <code>{runId}</code>
              </h2>
            </div>
            <span className="run-state">
              {status === null ? "Status unavailable" : stateLabels[status.state]}
            </span>
          </header>

          <div className="run-record-body">
            {isLoading && (
              <p className="run-monitor-status" role="status">
                Loading persisted run status…
              </p>
            )}

            {error !== null && (
              <div className="review-error" role="alert">
                <p>{runMonitorErrorMessage(error)}</p>
                {errorStatus === 401 && (
                  <a className="review-login-link" href="/api/v1/auth/login">
                    Sign in
                  </a>
                )}
                {lastUpdated !== null && (
                  <p>
                    Showing the last complete response from{" "}
                    {formatTimestamp(lastUpdated)}.
                  </p>
                )}
                <button
                  className="button button--secondary"
                  type="button"
                  onClick={() => setRefreshToken((token) => token + 1)}
                >
                  Retry now
                </button>
              </div>
            )}

            {status !== null && (
              <>
                <div className="run-summary">
                  <div>
                    <span className="run-summary-label">Connection</span>
                    <span>{connectionLabel}</span>
                  </div>
                  <div>
                    <span className="run-summary-label">Saved events</span>
                    <span>Through sequence {cursorRef.current}</span>
                  </div>
                  {lastUpdated !== null && (
                    <div>
                      <span className="run-summary-label">
                        Last complete refresh
                      </span>
                      <time dateTime={lastUpdated.toISOString()}>
                        {formatTimestamp(lastUpdated)}
                      </time>
                    </div>
                  )}
                </div>
                <p className="visually-hidden" role="status" aria-live="polite">
                  {announcement}
                </p>
                {connectionState === "live" &&
                  status.lastSequence > cursorRef.current && (
                    <p className="run-monitor-status" role="status">
                      Saved event history is catching up. Run status is shown
                      independently.
                    </p>
                  )}
                <RunEventTimeline
                  events={events}
                  hasOlderEvents={hasOlderEvents}
                />
              </>
            )}
          </div>
        </section>
      )}
    </section>
  );
}
