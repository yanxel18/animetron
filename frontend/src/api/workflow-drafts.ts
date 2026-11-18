import type { RevisionOutput, WorkflowDraftOutput, WorkflowValidationOutput } from "./generated";
import { revisionValid } from "./workflows";

export class WorkflowDraftError extends Error {
  readonly status: number | null;
  readonly uncertain: boolean;
  constructor(message: string, status: number | null = null, uncertain = false) {
    super(message);
    this.name = "WorkflowDraftError";
    this.status = status;
    this.uncertain = uncertain;
  }
}

const record = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
const uuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const version = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 2_147_483_647;

async function request(path: string, options: RequestInit, mutation = false): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { ...options, credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new WorkflowDraftError(
      mutation ? "The revision request outcome is unknown." : "The workflow service could not be reached.",
      null, mutation,
    );
  }
  if (!response.ok) {
    const uncertain = mutation && ![401, 403, 404, 409, 422].includes(response.status);
    throw new WorkflowDraftError(
      uncertain ? "The revision request outcome is unknown." : `The workflow service returned HTTP ${response.status}.`,
      response.status, uncertain,
    );
  }
  try {
    return await response.json() as unknown;
  } catch {
    throw new WorkflowDraftError("The workflow service returned an invalid response.", response.status, mutation);
  }
}

async function ownerCsrf(): Promise<string> {
  const session = record(await request("/api/v1/auth/session", {
    method: "GET", headers: { Accept: "application/json" },
  }));
  if (!session || !["owner", "operator", "viewer"].includes(String(session.role))) {
    throw new WorkflowDraftError("The session returned an invalid response; no change was submitted.");
  }
  if (session.role !== "owner") throw new WorkflowDraftError("Owner access is required.", 403);
  if (typeof session.csrfToken !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(session.csrfToken)) {
    throw new WorkflowDraftError("The session returned an invalid response; no change was submitted.");
  }
  return session.csrfToken;
}

function draft(value: unknown, id: string): WorkflowDraftOutput {
  const item = record(value);
  if (!item || item.workflowId !== id || typeof item.document !== "string" || !version(item.version)) {
    throw new WorkflowDraftError("The workflow service returned an invalid response.", 200);
  }
  return { workflowId: id, document: item.document, version: item.version };
}

function checkId(id: string): void {
  if (!uuid(id)) throw new WorkflowDraftError("Enter a valid lowercase workflow ID.", 422);
}

export async function readWorkflowDraft(id: string): Promise<WorkflowDraftOutput> {
  checkId(id);
  return draft(await request(`/api/v1/workflows/${id}/draft`, {
    method: "GET", headers: { Accept: "application/json" },
  }), id);
}

async function postVersion(id: string, endpoint: string, expectedVersion: number, mutation: boolean): Promise<unknown> {
  checkId(id);
  if (!version(expectedVersion) || expectedVersion >= 2_147_483_647) {
    throw new WorkflowDraftError("The draft version cannot be used.", 422);
  }
  const token = await ownerCsrf();
  return request(`/api/v1/workflows/${id}/${endpoint}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": token },
    body: JSON.stringify({ expectedVersion }),
  }, mutation);
}

export async function validateWorkflowDraft(id: string, expectedVersion: number): Promise<WorkflowValidationOutput> {
  const result = record(await postVersion(id, "validations", expectedVersion, false));
  if (!result || result.workflowId !== id || result.draftVersion !== expectedVersion ||
      typeof result.isValid !== "boolean" || !Array.isArray(result.issues) ||
      result.isValid !== (result.issues.length === 0) || !result.issues.every((value: unknown) => {
        const issue = record(value);
        return issue && typeof issue.code === "string" && typeof issue.message === "string" &&
          ["nodeId", "edgeId", "sourcePort", "targetPort"].every((key) =>
            issue[key] === undefined || issue[key] === null || typeof issue[key] === "string");
      })) {
    throw new WorkflowDraftError("The validation service returned an invalid response.");
  }
  return result as WorkflowValidationOutput;
}

export async function createDraftRevision(id: string, expectedVersion: number): Promise<RevisionOutput> {
  const result = record(await postVersion(id, "revisions", expectedVersion, true));
  if (!result || result.workflowId !== id || typeof result.revision !== "string" ||
      !revisionValid(result.revision) || typeof result.canonicalJson !== "string" ||
      !/^[\x00-\x7f]*$/.test(result.canonicalJson) ||
      typeof result.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(result.sha256)) {
    throw new WorkflowDraftError("The revision response could not be verified.", 200, true);
  }
  return result as RevisionOutput;
}
