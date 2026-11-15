import type { RunEventOutput, RunState } from "../api/generated";

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

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

interface RunEventTimelineProps {
  events: RunEventOutput[];
  hasOlderEvents: boolean;
}

export function RunEventTimeline({
  events,
  hasOlderEvents,
}: RunEventTimelineProps) {
  return (
    <section className="run-events" aria-labelledby="run-events-title">
      <div className="run-events-heading">
        <div>
          <p className="panel-kicker">ORDERED HISTORY</p>
          <h3 id="run-events-title">Saved events</h3>
        </div>
        <span className="panel-state">
          {events.length} {events.length === 1 ? "event" : "events"}
        </span>
      </div>
      {hasOlderEvents && (
        <p className="run-history-note" role="note">
          Showing the most recent 500 events. Earlier events are not displayed.
        </p>
      )}
      {events.length === 0 ? (
        <p className="run-monitor-status" role="status">
          No saved events have been recorded for this run.
        </p>
      ) : (
        <ol className="run-event-list" aria-label="Saved run events">
          {events.map((event) => (
            <li className="run-event" key={event.sequence}>
              <div className="run-event-meta">
                <span>Event {event.sequence}</span>
                <span>{stateLabels[event.state]}</span>
                <time dateTime={event.occurredAt}>
                  {formatTimestamp(event.occurredAt)}
                </time>
              </div>
              <p>{event.message}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
