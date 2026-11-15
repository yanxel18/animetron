import { useEffect, useRef, useState } from "react";

import type { OccurrenceOutput } from "../api/generated";
import { fetchSchedulePreview, ScheduleListError, scheduleErrorMessage } from "../api/schedules";

type Props = {
  id: string;
  onAccessDenied: (error: ScheduleListError) => void;
};

export function SchedulePreview({ id, onAccessDenied }: Props) {
  const [occurrences, setOccurrences] = useState<OccurrenceOutput[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => () => activeRequest.current?.abort(), []);

  async function preview() {
    if (activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setOccurrences(null);
    setError(null);
    setLoading(true);
    try {
      const result = await fetchSchedulePreview(id, controller.signal);
      if (!controller.signal.aborted) setOccurrences(result.occurrences);
    } catch (requestError) {
      if (controller.signal.aborted) return;
      if (requestError instanceof ScheduleListError &&
        (requestError.status === 401 || requestError.status === 403)) {
        onAccessDenied(requestError);
      } else {
        setError(requestError);
      }
    } finally {
      if (!controller.signal.aborted) {
        activeRequest.current = null;
        setLoading(false);
      }
    }
  }

  return (
    <div className="schedule-preview">
      <button
        className="button button--secondary"
        type="button"
        aria-label={`Preview next five for schedule ${id}`}
        disabled={loading}
        onClick={() => void preview()}
      >
        {loading ? "Loading preview..." : "Preview next five"}
      </button>
      <p className="visually-hidden" role="status">
        {loading ? "Loading schedule preview..." : occurrences !== null ? "Preview ready: five occurrences." : ""}
      </p>
      {error !== null && <p role="alert">{scheduleErrorMessage(error)}</p>}
      {occurrences !== null && (
        <div>
          <h3>Next five occurrences</h3>
          <p>
            Preview does not start a run. Times are calculated even for paused
            schedules. Current server settings may differ from the details above.
          </p>
          <ol className="schedule-occurrences">
            {occurrences.map((occurrence) => (
              <li key={occurrence.slotKey}>
                <span>Local: <time dateTime={occurrence.localTime}>{occurrence.localTime}</time></span>
                <span>UTC: <time dateTime={occurrence.dueAt}>{occurrence.dueAt}</time></span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
