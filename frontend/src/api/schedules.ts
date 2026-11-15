import type { DescriptorOutput, PageOutput, PreviewOutput } from "./generated";

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

async function previewRequest(
  url: string,
  options: RequestInit,
  signal?: AbortSignal,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, { ...options, credentials: "same-origin", cache: "no-store", signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ScheduleListError("The schedule service could not be reached.", null);
  }
  if (!response.ok) {
    throw new ScheduleListError(`The schedule service returned HTTP ${response.status}.`, response.status);
  }
  try {
    return await response.json() as unknown;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ScheduleListError("The schedule service returned an invalid response.", response.status);
  }
}

export async function fetchSchedulePreview(id: string, signal?: AbortSignal): Promise<PreviewOutput> {
  if (!isScheduleId(id)) throw new ScheduleListError("The schedule ID is invalid.", 422);
  const session = record(await previewRequest("/api/v1/auth/session", {
    method: "GET",
    headers: { Accept: "application/json" },
  }, signal));
  if (session === null || !["owner", "operator", "viewer"].includes(String(session.role))) {
    throw new ScheduleListError("The schedule service returned an invalid response.", 200);
  }
  if (session.role !== "owner") {
    throw new ScheduleListError("Owner access is required.", 403);
  }
  if (typeof session.csrfToken !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(session.csrfToken)) {
    throw new ScheduleListError("The schedule service returned an invalid response.", 200);
  }
  const result = record(await previewRequest(`/api/v1/schedules/${id}/previews`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": session.csrfToken,
    },
    body: "{}",
  }, signal));
  const occurrences = result?.occurrences;
  if (!Array.isArray(occurrences) || occurrences.length !== 5 ||
    !occurrences.every((value: unknown) => {
      const item = record(value);
      return item !== null && isTimestamp(item.localTime) && isTimestamp(item.dueAt) &&
        /(?:Z|\+00:00)$/i.test(item.dueAt) &&
        Date.parse(item.localTime) === Date.parse(item.dueAt) &&
        typeof item.slotKey === "string" && item.slotKey.length > 0;
    }) ||
    !occurrences.every((value, index) =>
      index === 0 || Date.parse(value.dueAt) > Date.parse(occurrences[index - 1].dueAt))) {
    throw new ScheduleListError("The schedule service returned an invalid response.", 200);
  }
  return { occurrences };
}

export function scheduleErrorMessage(error: unknown): string {
  if (!(error instanceof ScheduleListError)) return "Schedules could not be loaded.";
  if (error.status === null) return "The schedule service could not be reached.";
  if (error.status === 401) return "Sign in to view schedules.";
  if (error.status === 403) return "Access denied. Owner access and a valid session are required.";
  if (error.status === 503) return "The schedule service is unavailable. Try again.";
  if (error.message.includes("invalid response")) return error.message;
  return `Schedules could not be loaded (HTTP ${error.status}).`;
}
