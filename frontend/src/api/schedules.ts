import type { DescriptorOutput, PageOutput } from "./generated";

export class ScheduleListError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ScheduleListError";
    this.status = status;
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
}

function isScheduleId(value: unknown): value is string {
  return isUuid(value) && value[14] === "4" && /^[89ab]$/.test(value[19] ?? "");
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" &&
    /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) &&
    Number.isFinite(Date.parse(value));
}

function isDescriptor(value: unknown): value is DescriptorOutput {
  const item = record(value);
  return item !== null &&
    isScheduleId(item.id) &&
    isUuid(item.workflowId) &&
    typeof item.revision === "string" && item.revision.length > 0 &&
    typeof item.expression === "string" && item.expression.length > 0 &&
    typeof item.timeZone === "string" && item.timeZone.length > 0 &&
    typeof item.enabled === "boolean" &&
    (item.nextDueAt === null || isTimestamp(item.nextDueAt)) &&
    item.overlapPolicy === "skip" &&
    item.missedRunPolicy === "skip" &&
    typeof item.version === "number" &&
    Number.isInteger(item.version) && item.version >= 1 &&
    isTimestamp(item.createdAt) &&
    isTimestamp(item.updatedAt);
}

function isPage(value: unknown, cursor: string | null): value is PageOutput {
  const page = record(value);
  if (page === null || !Array.isArray(page.data) || page.data.length > 50 ||
      !page.data.every(isDescriptor)) return false;
  return page.nextCursor === null || (
    isScheduleId(page.nextCursor) &&
    page.nextCursor !== cursor &&
    page.data.length === 50 &&
    page.data[page.data.length - 1]?.id === page.nextCursor
  );
}

export async function fetchSchedulePage(
  cursor: string | null,
  signal?: AbortSignal,
): Promise<PageOutput> {
  if (cursor !== null && !isScheduleId(cursor)) {
    throw new ScheduleListError("The schedule cursor is invalid.", 422);
  }
  const query = new URLSearchParams({ limit: "50" });
  if (cursor !== null) query.set("cursor", cursor);

  let response: Response;
  try {
    response = await fetch(`/api/v1/schedules?${query}`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ScheduleListError("The schedule service could not be reached.", null);
  }
  if (!response.ok) {
    throw new ScheduleListError(
      `The schedule service returned HTTP ${response.status}.`,
      response.status,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ScheduleListError("The schedule service returned an invalid response.", response.status);
  }
  if (!isPage(payload, cursor)) {
    throw new ScheduleListError("The schedule service returned an invalid response.", response.status);
  }
  return payload;
}

export function scheduleErrorMessage(error: unknown): string {
  if (!(error instanceof ScheduleListError)) return "Schedules could not be loaded.";
  if (error.status === null) return "The schedule service could not be reached.";
  if (error.status === 401) return "Sign in to view schedules.";
  if (error.status === 403) return "Owner access is required to view schedules.";
  if (error.status === 503) return "The schedule service is unavailable. Try again.";
  if (error.message.includes("invalid response")) return error.message;
  return `Schedules could not be loaded (HTTP ${error.status}).`;
}
