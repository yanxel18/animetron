import type {
  RevisionOutput, WorkflowDraftInput, WorkflowDraftOutput, WorkflowValidationOutput,
} from "./generated";
import { revisionValid } from "./workflows";

export const PENDING_WORKFLOW_REVISION_KEY = "animetron.workflow-revision.pending.v1";
const REVISION_LOCK_NAME = "animetron-workflow-revision-v1";

export type PendingWorkflowRevision = {
  workflowId: string;
  expectedVersion: number;
};
export type PendingWorkflowRevisionState = PendingWorkflowRevision | null | "unavailable";

export class WorkflowDraftError extends Error {
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
    this.name = "WorkflowDraftError";
    this.status = status;
    this.uncertain = uncertain;
    this.requiresAcknowledgement = requiresAcknowledgement;
  }
}

const record = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
const uuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
const version = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 2_147_483_647;

export function readPendingWorkflowRevision(): PendingWorkflowRevisionState {
  try {
    const raw = window.localStorage.getItem(PENDING_WORKFLOW_REVISION_KEY);
    if (raw === null) return null;
    const value = record(JSON.parse(raw));
    if (!value || typeof value.workflowId !== "string" || !uuid(value.workflowId) ||
        !version(value.expectedVersion) || value.expectedVersion >= 2_147_483_647) {
      return "unavailable";
    }
    return { workflowId: value.workflowId, expectedVersion: value.expectedVersion };
  } catch {
    return "unavailable";
  }
}

function storePendingWorkflowRevision(attempt: PendingWorkflowRevision): void {
  try {
    window.localStorage.setItem(PENDING_WORKFLOW_REVISION_KEY, JSON.stringify(attempt));
    const stored = readPendingWorkflowRevision();
    if (stored === null || stored === "unavailable" ||
        stored.workflowId !== attempt.workflowId || stored.expectedVersion !== attempt.expectedVersion) {
      throw new Error("recovery marker read-back did not match");
    }
  } catch {
    throw new WorkflowDraftError(
      "Safe revision creation is unavailable because its recovery marker could not be saved; no request was sent.",
    );
  }
}

export function clearPendingWorkflowRevision(): boolean {
  try {
    window.localStorage.removeItem(PENDING_WORKFLOW_REVISION_KEY);
    return window.localStorage.getItem(PENDING_WORKFLOW_REVISION_KEY) === null;
  } catch {
    return false;
  }
}

async function request(
  path: string,
  options: RequestInit,
  mutation = false,
  uncertainMessage = "The revision request outcome is unknown.",
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { ...options, credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new WorkflowDraftError(
      mutation ? uncertainMessage : "The workflow service could not be reached.",
      null, mutation,
    );
  }
  if (!response.ok) {
    const uncertain = mutation && ![401, 403, 404, 409, 422].includes(response.status);
    throw new WorkflowDraftError(
      uncertain ? uncertainMessage : `The workflow service returned HTTP ${response.status}.`,
      response.status, uncertain,
    );
  }
  try {
    return await response.json() as unknown;
  } catch {
    throw new WorkflowDraftError(
      mutation ? uncertainMessage : "The workflow service returned an invalid response.",
      response.status, mutation,
    );
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

function draft(value: unknown, id: string, uncertain = false): WorkflowDraftOutput {
  const item = record(value);
  if (!item || item.workflowId !== id || typeof item.document !== "string" || !version(item.version)) {
    throw new WorkflowDraftError("The workflow service returned an invalid response.", 200, uncertain);
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

export async function saveWorkflowDraft(
  id: string,
  document: string,
  expectedVersion: number,
): Promise<WorkflowDraftOutput> {
  checkId(id);
  if (!version(expectedVersion) || expectedVersion >= 2_147_483_647) {
    throw new WorkflowDraftError("The draft version cannot be saved.", 422);
  }
  const token = await ownerCsrf();
  const body: WorkflowDraftInput = { document, expectedVersion };
  const result = draft(await request(`/api/v1/workflows/${id}/draft`, {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": token,
    },
    body: JSON.stringify(body),
  }, true, "The draft save outcome is unknown."), id, true);
  if (result.document !== document || result.version !== expectedVersion + 1) {
    throw new WorkflowDraftError("The draft save response could not be verified.", 200, true);
  }
  return result;
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

export async function createDraftRevision(
  id: string,
  expectedVersion: number,
  options: { acknowledgeUncertain?: boolean } = {},
): Promise<RevisionOutput> {
  checkId(id);
  if (!version(expectedVersion) || expectedVersion >= 2_147_483_647) {
    throw new WorkflowDraftError("The draft version cannot be used.", 422);
  }
  const locks = navigator.locks;
  if (!locks || typeof locks.request !== "function") {
    throw new WorkflowDraftError(
      "Safe revision creation is unavailable because this browser cannot coordinate attempts; no request was sent.",
    );
  }

  return locks.request(
    REVISION_LOCK_NAME,
    { mode: "exclusive", ifAvailable: true },
    async (lock) => {
      if (lock === null) {
        throw new WorkflowDraftError(
          "Another revision attempt is in progress in this browser. Wait for it to finish before starting another.",
        );
      }

      const previous = readPendingWorkflowRevision();
      if (previous === "unavailable") {
        throw new WorkflowDraftError(
          "Safe revision creation is unavailable because the previous attempt state cannot be read; no request was sent.",
        );
      }
      if (previous && previous.workflowId !== id) {
        throw new WorkflowDraftError(
          `Resolve the uncertain revision attempt for workflow ${previous.workflowId} before creating a revision for another workflow.`,
          null,
          true,
          true,
        );
      }
      if (previous && !options.acknowledgeUncertain) {
        throw new WorkflowDraftError(
          "A previous revision attempt has an uncertain outcome. Inspect saved revisions before explicitly acknowledging a possible duplicate.",
          null,
          true,
          true,
        );
      }

      let token: string;
      try {
        token = await ownerCsrf();
      } catch (error) {
        if (error instanceof WorkflowDraftError && (error.status === 401 || error.status === 403)) {
          clearPendingWorkflowRevision();
        }
        throw error;
      }

      const attempt = { workflowId: id, expectedVersion };
      storePendingWorkflowRevision(attempt);
      try {
        const result = record(await request(`/api/v1/workflows/${id}/revisions`, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
          },
          body: JSON.stringify({ expectedVersion }),
        }, true));
        if (!result || result.workflowId !== id || typeof result.revision !== "string" ||
            !revisionValid(result.revision) || typeof result.canonicalJson !== "string" ||
            !/^[\x00-\x7f]*$/.test(result.canonicalJson) ||
            typeof result.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(result.sha256)) {
          throw new WorkflowDraftError("The revision response could not be verified.", 200, true);
        }
        clearPendingWorkflowRevision();
        return result as RevisionOutput;
      } catch (error) {
        if (error instanceof WorkflowDraftError && !error.uncertain) {
          if (error.status === 401 || error.status === 403) {
            clearPendingWorkflowRevision();
          } else if (previous) {
            storePendingWorkflowRevision(previous);
          } else {
            clearPendingWorkflowRevision();
          }
        }
        throw error;
      }
    },
  );
}
