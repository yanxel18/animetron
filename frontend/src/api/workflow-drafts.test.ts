import { afterEach, expect, it, vi } from "vitest";
import {
  createDraftRevision, readWorkflowDraft, validateWorkflowDraft,
} from "./workflow-drafts";

const id = "12345678-1234-4234-8234-123456789abc";
const json = (value: unknown) => new Response(JSON.stringify(value));
const session = { role: "owner", csrfToken: "test-csrf" };
afterEach(() => vi.unstubAllGlobals());

it("reads a draft and validates the server response", async () => {
  const fetcher = vi.fn().mockResolvedValue(json({ workflowId: id, document: "{}", version: 2 }));
  vi.stubGlobal("fetch", fetcher);
  expect(await readWorkflowDraft(id)).toEqual({ workflowId: id, document: "{}", version: 2 });
  expect(fetcher).toHaveBeenCalledWith(
    `/api/v1/workflows/${id}/draft`,
    expect.objectContaining({ method: "GET", credentials: "same-origin", cache: "no-store" }),
  );
});

it("validates a saved version and creates its revision with separate requests", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, draftVersion: 1, isValid: true, issues: [] }))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, revision: "r1", canonicalJson: "{}", sha256: "a".repeat(64) }));
  vi.stubGlobal("fetch", fetcher);
  expect((await validateWorkflowDraft(id, 1)).isValid).toBe(true);
  expect((await createDraftRevision(id, 1)).revision).toBe("r1");
  expect(fetcher.mock.calls[3][0]).toBe(`/api/v1/workflows/${id}/revisions`);
  expect(fetcher.mock.calls[3][1].body).toBe('{"expectedVersion":1}');
  expect(fetcher.mock.calls[3][1]).toEqual(expect.objectContaining({
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: expect.objectContaining({ "X-CSRF-Token": "test-csrf" }),
  }));
});

it("distinguishes confirmed conflicts from uncertain mutation outcomes", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(new Response("", { status: 409 }))
    .mockResolvedValueOnce(json(session))
    .mockRejectedValueOnce(new Error("connection lost"));
  vi.stubGlobal("fetch", fetcher);
  await expect(createDraftRevision(id, 1)).rejects.toMatchObject({ status: 409, uncertain: false });
  await expect(createDraftRevision(id, 1)).rejects.toMatchObject({ status: null, uncertain: true });
});

it("rejects malformed or mismatched successful mutation responses as uncertain", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, revision: "r", canonicalJson: {}, sha256: "a".repeat(64) })));
  await expect(createDraftRevision(id, 1)).rejects.toMatchObject({ uncertain: true });
});

it("does not submit a mutation when the session is not an owner", async () => {
  const fetcher = vi.fn().mockResolvedValue(json({ role: "viewer", csrfToken: "test-csrf" }));
  vi.stubGlobal("fetch", fetcher);
  await expect(createDraftRevision(id, 1)).rejects.toMatchObject({ status: 403, uncertain: false });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
