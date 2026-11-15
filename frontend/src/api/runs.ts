import type {
  RunEventOutput,
  RunEventPageOutput,
  RunState,
  RunStatusOutput,
} from "./generated";

const runStates: ReadonlySet<string> = new Set<RunState>([
  "QUEUED",
  "RUNNING",
  "WAITING_REVIEW",
  "SUCCEEDED",
  "PARTIAL_FAILURE",
  "FAILED",
  "CANCELLING",
  "CANCELLED",
]);
const maximumSequence = 2_147_483_647;

export class RunMonitorError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "RunMonitorError";
    this.status = status;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isRunId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  );
}

function isSequence(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= maximumSequence
  );
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    Number.isFinite(Date.parse(value)) &&
    /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  );
}

function isRunStatus(
  value: unknown,
  expectedRunId: string,
): value is RunStatusOutput {
  const record = asRecord(value);
  return (
    record !== null &&
    isRunId(record.runId) &&
    record.runId.toLowerCase() === expectedRunId.toLowerCase() &&
    typeof record.state === "string" &&
    runStates.has(record.state) &&
    isSequence(record.lastSequence)
  );
}

function isRunEvent(
  value: unknown,
  expectedRunId: string,
  afterSequence: number,
  previousSequence: number,
): value is RunEventOutput {
  const record = asRecord(value);
  return (
    record !== null &&
    isRunId(record.runId) &&
    record.runId.toLowerCase() === expectedRunId.toLowerCase() &&
    isSequence(record.sequence) &&
    record.sequence > afterSequence &&
    record.sequence > previousSequence &&
    typeof record.state === "string" &&
    runStates.has(record.state) &&
    typeof record.message === "string" &&
    isTimestamp(record.occurredAt)
  );
}

function isRunEventPage(
  value: unknown,
  runId: string,
  afterSequence: number,
): value is RunEventPageOutput {
  const record = asRecord(value);
  if (
    record === null ||
    !Array.isArray(record.data) ||
    record.data.length > 100 ||
    typeof record.hasMore !== "boolean" ||
    !isSequence(record.nextAfterSequence)
  ) {
    return false;
  }

  let previousSequence = afterSequence;
  for (const event of record.data) {
    if (!isRunEvent(event, runId, afterSequence, previousSequence)) return false;
    previousSequence = event.sequence;
  }

  const expectedCursor =
    record.data.length === 0
      ? afterSequence
      : previousSequence;
  return (
    record.nextAfterSequence === expectedCursor &&
    (!record.hasMore || record.data.length > 0)
  );
}

async function getJson(
  path: string,
  signal?: AbortSignal,
): Promise<{ payload: unknown; status: number }> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new RunMonitorError("The run service could not be reached.", null);
  }

  if (!response.ok) {
    throw new RunMonitorError(
      `The run service returned HTTP ${response.status}.`,
      response.status,
    );
  }

  try {
    return { payload: await response.json(), status: response.status };
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new RunMonitorError(
      "The run service returned an invalid response.",
      response.status,
    );
  }
}

function validateRunId(runId: string): void {
  if (!isRunId(runId)) {
    throw new RunMonitorError("Enter a valid run ID.", 422);
  }
}

export async function fetchRunStatus(
  runId: string,
  signal?: AbortSignal,
): Promise<RunStatusOutput> {
  validateRunId(runId);
  const { payload, status } = await getJson(
    `/api/v1/runs/${encodeURIComponent(runId)}`,
    signal,
  );
  if (!isRunStatus(payload, runId)) {
    throw new RunMonitorError(
      "The run service returned an invalid response.",
      status,
    );
  }
  return payload;
}

export async function fetchRunEvents(
  runId: string,
  afterSequence: number,
  signal?: AbortSignal,
): Promise<RunEventPageOutput> {
  validateRunId(runId);
  if (!isSequence(afterSequence)) {
    throw new RunMonitorError("The event cursor is invalid.", 422);
  }

  const query = new URLSearchParams({
    afterSequence: String(afterSequence),
    limit: "100",
  });
  const { payload, status } = await getJson(
    `/api/v1/runs/${encodeURIComponent(runId)}/events?${query}`,
    signal,
  );
  if (!isRunEventPage(payload, runId, afterSequence)) {
    throw new RunMonitorError(
      "The run service returned an invalid response.",
      status,
    );
  }
  return payload;
}

export function runMonitorErrorMessage(error: unknown): string {
  if (!(error instanceof RunMonitorError)) {
    return "Run status could not be loaded.";
  }
  if (error.status === null) {
    return "The run service could not be reached.";
  }
  if (error.status === 401) {
    return "Sign in to view run history.";
  }
  if (error.status === 403) {
    return "Owner access is required to view run history.";
  }
  if (error.status === 404) {
    return "The run was not found or is no longer available.";
  }
  if (error.status === 503) {
    return "The run service is unavailable. Try again.";
  }
  if (error.message.includes("invalid response")) {
    return error.message;
  }
  return `Run data could not be loaded (HTTP ${error.status}).`;
}
