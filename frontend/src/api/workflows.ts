import type { RevisionListOutput, RevisionOutput, SampleNodeCatalogOutput, WorkflowIdListOutput } from "./generated";

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

async function request(path: string, signal?: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
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

export async function fetchSampleNodeCatalog(signal?: AbortSignal): Promise<SampleNodeCatalogOutput> {
  const data = record(await request("/api/v1/workflows/node-types", signal));
  const text = (value: unknown) => typeof value === "string" && value.length > 0 && value.length <= 256;
  const ports = (value: unknown) => Array.isArray(value) && value.length <= 64 &&
    value.every((port) => {
      const item = record(port);
      return item !== null && text(item.name) && text(item.type) && typeof item.required === "boolean";
    }) && new Set(value.map((port) => record(port)?.name)).size === value.length;
  if (!data || data.scope !== "sample-validation" || !Array.isArray(data.nodes) || data.nodes.length > 100 ||
      !data.nodes.every((value) => {
        const node = record(value);
        return node !== null && text(node.type) && ports(node.inputs) && ports(node.outputs) &&
          (node.configSchema === null || (record(node.configSchema) !== null && JSON.stringify(node.configSchema).length <= 65_536));
      }) || new Set(data.nodes.map((value: unknown) => record(value)?.type)).size !== data.nodes.length) {
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
  return data as SampleNodeCatalogOutput;
}

function pageUrl(path: string, cursor: string | null, max: number): string {
  if (cursor !== null && !cursorValid(cursor, max)) throw new WorkflowDiscoveryError("Invalid cursor.");
  const query = new URLSearchParams({ limit: "50" });
  if (cursor !== null) query.set("cursor", cursor);
  return `${path}?${query}`;
}

export function revisionValid(value: string): boolean {
  const points = Array.from(value);
  return points.length > 0 && points.length <= 128 &&
    !/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/u.test(value) && !value.includes("\0") &&
    points.every((point) => !(point.length === 1 && point.charCodeAt(0) >= 0xd800 && point.charCodeAt(0) <= 0xdfff));
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
  const value = pageShape(await request(pageUrl("/api/v1/workflows", cursor, 128), signal), cursor, 128);
  const data = value.data as unknown[];
  if (!data.every((item) => uuid(record(item)?.workflowId)) ||
      new Set(data.map((item) => record(item)?.workflowId)).size !== data.length) {
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
  return value as WorkflowIdListOutput;
}

export async function fetchRevisionPage(id: string, cursor: string | null, signal?: AbortSignal): Promise<RevisionListOutput> {
  if (!uuid(id)) throw new WorkflowDiscoveryError("Invalid workflow ID.");
  const value = pageShape(await request(pageUrl(`/api/v1/workflows/${encodeURIComponent(id)}/revisions`, cursor, 2304), signal), cursor, 2304);
  const data = value.data as unknown[];
  if (!data.every((item) => {
    const revision = record(item);
    return revision?.workflowId === id && typeof revision.revision === "string" &&
      revisionValid(revision.revision) &&
      typeof revision.createdAt === "string" && /(?:Z|[+-]\d{2}:\d{2})$/i.test(revision.createdAt) &&
      Number.isFinite(Date.parse(revision.createdAt));
  }) || new Set(data.map((item) => record(item)?.revision)).size !== data.length) {
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
  return value as RevisionListOutput;
}

export async function fetchRevision(id: string, revision: string, signal?: AbortSignal): Promise<RevisionOutput> {
  if (!uuid(id) || !revisionValid(revision)) throw new WorkflowDiscoveryError("Invalid revision selection.");
  const query = new URLSearchParams({ revision });
  const value = record(await request(`/api/v1/workflows/${encodeURIComponent(id)}/revision?${query}`, signal));
  if (!value || value.workflowId !== id || value.revision !== revision ||
      typeof value.canonicalJson !== "string" || !/^[\x00-\x7f]*$/.test(value.canonicalJson) ||
      typeof value.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.sha256)) {
    throw new WorkflowDiscoveryError("The workflow service returned an invalid response.");
  }
  return value as RevisionOutput;
}
