import type {
  ReviewDestinationResponse,
  ReviewMetadataResponse,
  ReviewPageResponse,
  ReviewState,
} from "./generated";

const reviewStates: ReadonlySet<string> = new Set<ReviewState>([
  "PENDING_DELIVERY",
  "AWAITING_DECISION",
  "APPROVED",
  "REJECTED",
  "EXPIRED",
  "SUPERSEDED",
  "DELIVERY_FAILED",
  "DELIVERY_UNKNOWN",
]);

export class ReviewQueueError extends Error {
  readonly status: number | null;

  constructor(
    message: string,
    status: number | null,
  ) {
    super(message);
    this.name = "ReviewQueueError";
    this.status = status;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isUuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  );
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function isDestination(value: unknown): value is ReviewDestinationResponse {
  const record = asRecord(value);
  return (
    record !== null &&
    typeof record.provider === "string" &&
    record.provider.length > 0 &&
    typeof record.accountId === "string" &&
    record.accountId.length > 0
  );
}

function isReviewMetadata(
  value: unknown,
): value is ReviewMetadataResponse {
  const record = asRecord(value);
  return (
    record !== null &&
    isUuid(record.id) &&
    isUuid(record.runId) &&
    typeof record.artifactRevision === "string" &&
    record.artifactRevision.length > 0 &&
    isSha256(record.artifactSha256) &&
    isSha256(record.captionSha256) &&
    Array.isArray(record.destinations) &&
    record.destinations.every(isDestination) &&
    isTimestamp(record.expiresAt) &&
    isTimestamp(record.createdAt) &&
    typeof record.state === "string" &&
    reviewStates.has(record.state) &&
    isTimestamp(record.stateChangedAt) &&
    (record.deliveryErrorCode === null ||
      typeof record.deliveryErrorCode === "string")
  );
}

function isReviewPage(value: unknown): value is ReviewPageResponse {
  const record = asRecord(value);
  return (
    record !== null &&
    Array.isArray(record.data) &&
    record.data.length <= 100 &&
    record.data.every(isReviewMetadata) &&
    (record.nextCursor === null ||
      (typeof record.nextCursor === "string" &&
        record.nextCursor.length > 0 &&
        record.nextCursor.length <= 128))
  );
}

export async function fetchReviewPage(
  cursor: string | null,
  signal?: AbortSignal,
): Promise<ReviewPageResponse> {
  const query = new URLSearchParams({ limit: "50" });
  if (cursor !== null) query.set("cursor", cursor);

  let response: Response;
  try {
    response = await fetch(`/api/v1/reviews?${query}`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ReviewQueueError("The review service could not be reached.", null);
  }

  if (!response.ok) {
    throw new ReviewQueueError(
      `The review service returned HTTP ${response.status}.`,
      response.status,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ReviewQueueError(
      "The review service returned an invalid response.",
      response.status,
    );
  }
  if (!isReviewPage(payload)) {
    throw new ReviewQueueError(
      "The review service returned an invalid response.",
      response.status,
    );
  }

  return payload;
}

export function reviewQueueErrorMessage(error: unknown): string {
  if (!(error instanceof ReviewQueueError)) {
    return "The review queue could not be loaded.";
  }
  if (error.status === null) {
    return "The review service could not be reached.";
  }
  if (error.status === 401) {
    return "Sign in to view review requests.";
  }
  if (error.status === 403) {
    return "Owner access is required to view review requests.";
  }
  if (error.status === 503) {
    return "The review service is unavailable. Try again.";
  }
  if (error.message.includes("invalid response")) {
    return error.message;
  }
  return `Review requests could not be loaded (HTTP ${error.status}).`;
}
