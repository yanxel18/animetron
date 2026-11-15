import type { DescriptorInput, DescriptorOutput } from "./generated";
import { revisionValid } from "./workflows";

export const SCHEDULE_CREATE_PENDING_KEY = "animetron.schedule-create.pending.v1";
const LOCK_NAME = "animetron-schedule-create-v1";
const PENDING_VALUE = "pending";

export class ScheduleCreateError extends Error {
  readonly status: number | null;
  readonly uncertain: boolean;
  readonly requiresAcknowledgement: boolean;

  constructor(
    message: string,
    status: number | null = null,
    uncertain = false,
    requiresAcknowledgement = false,
  ) {
    super(message);
    this.name = "ScheduleCreateError";
    this.status = status;
    this.uncertain = uncertain;
    this.requiresAcknowledgement = requiresAcknowledgement;
  }
}

export type ScheduleCreateIntent = "pending" | "none" | "unavailable";

export function readScheduleCreateIntent(): ScheduleCreateIntent {
  try {
    return window.localStorage.getItem(SCHEDULE_CREATE_PENDING_KEY) === null
      ? "none"
      : "pending";
  } catch {
    return "unavailable";
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function uuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
}

function scheduleId(value: unknown): value is string {
  return uuid(value) && value[14] === "4" && /^[89ab]$/.test(value[19] ?? "");
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" &&
    /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) &&
    Number.isFinite(Date.parse(value));
}

function descriptor(value: unknown): value is DescriptorOutput {
  const item = record(value);
  return item !== null &&
    scheduleId(item.id) &&
    uuid(item.workflowId) &&
    typeof item.revision === "string" && revisionValid(item.revision) &&
    typeof item.expression === "string" &&
    codePointLength(item.expression) >= 1 && codePointLength(item.expression) <= 256 &&
    typeof item.timeZone === "string" &&
    codePointLength(item.timeZone) >= 1 && codePointLength(item.timeZone) <= 255 &&
    typeof item.enabled === "boolean" &&
    (item.nextDueAt === null || timestamp(item.nextDueAt)) &&
    item.overlapPolicy === "skip" &&
    item.missedRunPolicy === "skip" &&
    Number.isInteger(item.version) && Number(item.version) >= 1 &&
    timestamp(item.createdAt) && timestamp(item.updatedAt);
}

function codePointLength(value: string): number {
  return Array.from(value).length;
}

function validInput(value: DescriptorInput): boolean {
  if (typeof value !== "object" || value === null) return false;
  return uuid(value.workflowId) &&
    typeof value.revision === "string" && revisionValid(value.revision) &&
    typeof value.expression === "string" &&
    codePointLength(value.expression) >= 1 &&
    codePointLength(value.expression) <= 256 &&
    typeof value.timeZone === "string" &&
    codePointLength(value.timeZone) >= 1 &&
    codePointLength(value.timeZone) <= 255 &&
    typeof value.enabled === "boolean" &&
    value.overlapPolicy === "skip" &&
    value.missedRunPolicy === "skip";
}

function assertSameOriginPath(path: string): void {
  if (!path.startsWith("/") || path.startsWith("//") ||
      new URL(path, window.location.href).origin !== window.location.origin) {
    throw new ScheduleCreateError("The schedule service URL is invalid; no request was sent.");
  }
}

function requestFailure(status: number): ScheduleCreateError {
  if (status === 401) {
    return new ScheduleCreateError("Your owner session expired. Sign in again.", status);
  }
  if (status === 403) {
    return new ScheduleCreateError("Owner access or request authorization was denied.", status);
  }
  if (status === 404) {
    return new ScheduleCreateError(
      "The selected saved workflow revision no longer exists. No schedule was created.",
      status,
    );
  }
  if (status === 409) {
    return new ScheduleCreateError(
      "The schedule request conflicts with current server state. No schedule was created.",
      status,
    );
  }
  if (status === 422) {
    return new ScheduleCreateError(
      "The server rejected the schedule settings. Check the fields and try a new submission.",
      status,
    );
  }
  return new ScheduleCreateError(
    `The schedule service returned HTTP ${status}. The outcome is uncertain; a schedule may have been saved. Do not retry automatically. Starting a new attempt could create a duplicate.`,
    status,
    true,
  );
}

const knownRejections = new Set([401, 403, 404, 409, 422]);

async function ownerCsrf(): Promise<string> {
  const path = "/api/v1/auth/session";
  assertSameOriginPath(path);
  let response: Response;
  try {
    response = await fetch(path, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
  } catch {
    throw new ScheduleCreateError("The owner session could not be checked; no schedule was submitted.");
  }
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) throw requestFailure(response.status);
    throw new ScheduleCreateError(
      `The owner session check returned HTTP ${response.status}; no schedule was submitted.`,
      response.status,
    );
  }

  let session: unknown;
  try {
    session = await response.json() as unknown;
  } catch {
    throw new ScheduleCreateError("The owner session returned an invalid response; no schedule was submitted.");
  }
  const value = record(session);
  if (!value || !["owner", "operator", "viewer"].includes(String(value.role))) {
    throw new ScheduleCreateError("The owner session returned an invalid response; no schedule was submitted.");
  }
  if (value.role !== "owner") {
    throw new ScheduleCreateError("Owner access is required to create schedules.", 403);
  }
  if (typeof value.csrfToken !== "string" ||
      !/^[A-Za-z0-9_-]{1,64}$/.test(value.csrfToken)) {
    throw new ScheduleCreateError("The owner session returned an invalid response; no schedule was submitted.");
  }
  return value.csrfToken;
}

function markPending(): void {
  try {
    window.localStorage.setItem(SCHEDULE_CREATE_PENDING_KEY, PENDING_VALUE);
    if (window.localStorage.getItem(SCHEDULE_CREATE_PENDING_KEY) !== PENDING_VALUE) {
      throw new Error("storage read-back did not match");
    }
  } catch {
    throw new ScheduleCreateError(
      "Safe creation is unavailable because the pending-attempt marker could not be saved; no schedule was submitted.",
    );
  }
}

function clearPending(): void {
  try {
    window.localStorage.removeItem(SCHEDULE_CREATE_PENDING_KEY);
  } catch {
    // Keeping a stale marker only requires explicit acknowledgement later.
  }
}

export async function createScheduleDescriptor(
  input: DescriptorInput,
  options: { acknowledgeUncertain?: boolean } = {},
): Promise<DescriptorOutput> {
  if (!validInput(input)) {
    throw new ScheduleCreateError("The schedule fields do not match the descriptor contract.", 422);
  }
  const locks = navigator.locks;
  if (!locks || typeof locks.request !== "function") {
    throw new ScheduleCreateError(
      "Safe creation is unavailable because this browser cannot coordinate schedule attempts; no request was sent.",
    );
  }

  try {
    return await locks.request(
      LOCK_NAME,
      { mode: "exclusive", ifAvailable: true },
      async (lock) => {
        if (lock === null) {
          throw new ScheduleCreateError(
            "Another schedule creation is in progress in this browser. Wait for it to finish before starting a new attempt.",
          );
        }
        const intent = readScheduleCreateIntent();
        if (intent === "unavailable") {
          throw new ScheduleCreateError(
            "Safe creation is unavailable because the pending-attempt marker cannot be read; no request was sent.",
          );
        }
        if (intent === "pending" && !options.acknowledgeUncertain) {
          throw new ScheduleCreateError(
            "A previous schedule creation has an uncertain outcome. A matching list item cannot prove which attempt created it. Review the list if useful, then explicitly acknowledge that a new attempt may create a duplicate.",
            null,
            true,
            true,
          );
        }
        const priorUncertainAttempt = intent === "pending";

        const csrfToken = await ownerCsrf();
        const path = "/api/v1/schedules";
        assertSameOriginPath(path);
        markPending();

        let response: Response;
        try {
          response = await fetch(path, {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            headers: {
              Accept: "application/json",
              "Content-Type": "application/json",
              "X-CSRF-Token": csrfToken,
            },
            body: JSON.stringify(input),
          });
        } catch {
          throw new ScheduleCreateError(
            "The schedule request could not be confirmed. It may have been saved. Do not retry automatically; a new attempt could create a duplicate.",
            null,
            true,
          );
        }

        if (response.status !== 201) {
          const error = requestFailure(response.status);
          if (knownRejections.has(response.status) && !priorUncertainAttempt) clearPending();
          throw error;
        }

        let payload: unknown;
        try {
          payload = await response.json() as unknown;
        } catch {
          throw new ScheduleCreateError(
            "The server may have created the schedule, but its response could not be verified. Do not retry automatically; a new attempt could create a duplicate.",
            response.status,
            true,
          );
        }
        if (!descriptor(payload) ||
            payload.workflowId !== input.workflowId ||
            payload.revision !== input.revision ||
            payload.expression !== input.expression ||
            payload.timeZone !== input.timeZone ||
            payload.enabled !== input.enabled) {
          throw new ScheduleCreateError(
            "The server may have created the schedule, but its response did not match the submitted descriptor. Do not retry automatically; a new attempt could create a duplicate.",
            response.status,
            true,
          );
        }
        if (!priorUncertainAttempt) clearPending();
        return payload;
      },
    );
  } catch (error) {
    if (error instanceof ScheduleCreateError) throw error;
    throw new ScheduleCreateError(
      "Safe creation could not obtain the browser attempt lock; no request was submitted.",
    );
  }
}
