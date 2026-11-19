import type { ArtifactMetadataOutput } from "./generated";

const uuid4Pattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const identifierPattern = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$/;
const mediaTypePattern =
  /^[a-z0-9][a-z0-9!#$&^_.+-]*\/[a-z0-9][a-z0-9!#$&^_.+-]*$/;

export class ArtifactMetadataError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null) {
    super(message);
    this.name = "ArtifactMetadataError";
    this.status = status;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function isArtifactId(value: string): boolean {
  return uuid4Pattern.test(value);
}

function isArtifactMetadata(
  value: unknown,
  expectedId: string,
): value is ArtifactMetadataOutput {
  const record = asRecord(value);
  return (
    record !== null &&
    Object.keys(record).length === 6 &&
    typeof record.id === "string" &&
    isArtifactId(record.id) &&
    record.id.toLowerCase() === expectedId.toLowerCase() &&
    typeof record.ownerId === "string" &&
    identifierPattern.test(record.ownerId) &&
    typeof record.revision === "string" &&
    identifierPattern.test(record.revision) &&
    typeof record.sha256 === "string" &&
    /^[a-f0-9]{64}$/.test(record.sha256) &&
    typeof record.byteSize === "number" &&
    Number.isSafeInteger(record.byteSize) &&
    record.byteSize >= 0 &&
    typeof record.mediaType === "string" &&
    record.mediaType.length <= 255 &&
    mediaTypePattern.test(record.mediaType)
  );
}

export async function fetchArtifactMetadata(
  artifactId: string,
  signal?: AbortSignal,
): Promise<ArtifactMetadataOutput> {
  if (!isArtifactId(artifactId)) {
    throw new ArtifactMetadataError("Enter a valid artifact ID.", 422);
  }

  let response: Response;
  try {
    response = await fetch(
      `/api/v1/artifacts/${encodeURIComponent(artifactId)}`,
      {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal,
      },
    );
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ArtifactMetadataError(
      "The artifact service could not be reached.",
      null,
    );
  }

  if (!response.ok) {
    throw new ArtifactMetadataError(
      `The artifact service returned HTTP ${response.status}.`,
      response.status,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ArtifactMetadataError(
      "The artifact service returned an invalid response.",
      response.status,
    );
  }

  if (!isArtifactMetadata(payload, artifactId)) {
    throw new ArtifactMetadataError(
      "The artifact service returned an invalid response.",
      response.status,
    );
  }

  return payload;
}

export function artifactMetadataErrorMessage(error: unknown): string {
  if (!(error instanceof ArtifactMetadataError)) {
    return "Artifact metadata could not be loaded.";
  }
  if (error.status === null) {
    return "The artifact service could not be reached.";
  }
  if (error.status === 401) {
    return "Sign in to view artifact metadata.";
  }
  if (error.status === 403) {
    return "Owner access is required to view artifact metadata.";
  }
  if (error.status === 404) {
    return "The artifact was not found or is unavailable.";
  }
  if (error.status === 503) {
    return "Artifact metadata is unavailable. Try again.";
  }
  if (error.status === 422 && error.message === "Enter a valid artifact ID.") {
    return error.message;
  }
  if (error.message.includes("invalid response")) {
    return error.message;
  }
  return `Artifact metadata could not be loaded (HTTP ${error.status}).`;
}
