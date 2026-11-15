import type { RevisionListOutput, WorkflowIdListOutput } from "./generated";

export class WorkflowDiscoveryError extends Error {
  readonly status: number | null;
  constructor(message: string, status: number | null = null) {
    super(message);
    this.status = status;
  }
}

const uuid = (value: unknown): value is string =>
  typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const record = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
const cursorValid = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= max && /^[A-Za-z0-9_-]+$/.test(value);

async function request(path: string, cursor: string | null, max: number, signal?: AbortSignal): Promise<unknown> {
  if (cursor !== null && !cursorValid(cursor, max)) throw new WorkflowDiscoveryError("Invalid cursor.");
  const query = new URLSearchParams({ limit: "50" });
  if (cursor !== null) query.set("cursor", cursor);
  let response: Response;
  try {
    response = await fetch(`${path}?${query}`, {
      method: "GET", credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json" }, signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new WorkflowDiscoveryError("The workflow service could not be reached.");
  }
  if (!response.ok) throw new WorkflowDiscoveryError(`The workflow service returned HTTP ${response.status}.`, response.status);
  try {
    return await response.json() as unknown;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
}

function pageShape(value: unknown, cursor: string | null, max: number): Record<string, unknown> {
  const page = record(value);
  if (!page || !Array.isArray(page.data) || page.data.length > 50 ||
      !(page.nextCursor === null || (cursorValid(page.nextCursor, max) &&
        page.nextCursor !== cursor && page.data.length === 50))) {
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
  return page;
}

export async function fetchWorkflowPage(cursor: string | null, signal?: AbortSignal): Promise<WorkflowIdListOutput> {
  const value = pageShape(await request("/api/v1/workflows", cursor, 128, signal), cursor, 128);
  const data = value.data as unknown[];
  if (!data.every((item) => uuid(record(item)?.workflowId)) ||
      new Set(data.map((item) => record(item)?.workflowId)).size !== data.length) {
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
  return value as WorkflowIdListOutput;
}

export async function fetchRevisionPage(id: string, cursor: string | null, signal?: AbortSignal): Promise<RevisionListOutput> {
  if (!uuid(id)) throw new WorkflowDiscoveryError("Invalid workflow ID.");
  const value = pageShape(await request(`/api/v1/workflows/${encodeURIComponent(id)}/revisions`, cursor, 2304, signal), cursor, 2304);
  const data = value.data as unknown[];
  if (!data.every((item) => {
    const revision = record(item);
    return revision?.workflowId === id && typeof revision.revision === "string" &&
      revision.revision.length > 0 && revision.revision.length <= 256 &&
      Array.from(revision.revision).length <= 128 &&
      typeof revision.createdAt === "string" && /(?:Z|[+-]\d{2}:\d{2})$/i.test(revision.createdAt) &&
      Number.isFinite(Date.parse(revision.createdAt));
  }) || new Set(data.map((item) => record(item)?.revision)).size !== data.length) {
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
  return value as RevisionListOutput;
}
