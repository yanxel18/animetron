import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WorkflowDraftPanel } from "./WorkflowDraftPanel";

const id = "12345678-1234-4234-8234-123456789abc";
const pendingKey = "animetron.workflow-revision.pending.v1";
const json = (value: unknown) => new Response(JSON.stringify(value));
const session = { role: "owner", csrfToken: "test-csrf" };
const draft = { workflowId: id, version: 3, document: '{"revision":"r1"}' };
beforeEach(() => {
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: vi.fn(async (_name: string, _options: unknown, callback: (lock: Lock | null) => Promise<unknown>) =>
        callback({ name: "test-lock", mode: "exclusive" } as Lock)),
    },
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.removeItem(pendingKey);
  Reflect.deleteProperty(navigator, "locks");
});

it("loads, validates and creates a revision of the exact saved draft", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, draftVersion: 3, isValid: true, issues: [] }))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, revision: "r1", canonicalJson: "{}", sha256: "a".repeat(64) }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  expect(await screen.findByLabelText("Workflow draft JSON")).toHaveValue(draft.document);
  await user.click(screen.getByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByText(/valid for version 3/i)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Create immutable revision" }));
  expect(await screen.findByText(/revision saved/i)).toBeInTheDocument();
  expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  expect(screen.getByLabelText("Created revision canonical JSON")).toHaveTextContent("{}");
  expect(fetcher.mock.calls[4][1].body).toBe('{"expectedVersion":3}');
});

it("saves edits before validating or creating a revision", async () => {
  const edited = '{"revision":"r2"}';
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, document: edited, version: 4 }))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, draftVersion: 4, isValid: true, issues: [] }))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, revision: "r2", canonicalJson: edited, sha256: "b".repeat(64) }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  const editor = await screen.findByLabelText("Workflow draft JSON");
  await user.clear(editor);
  await user.paste(edited);

  expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();
  expect(screen.getByLabelText("Workflow ID")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Load draft" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Create immutable revision" })).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText(/saved as version 4/i)).toBeInTheDocument();
  expect(fetcher.mock.calls[2][0]).toBe(`/api/v1/workflows/${id}/draft`);
  expect(fetcher.mock.calls[2][1].method).toBe("PUT");
  expect(fetcher.mock.calls[2][1].body).toBe(JSON.stringify({ document: edited, expectedVersion: 3 }));

  await user.click(screen.getByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByText(/valid for version 4/i)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Create immutable revision" }));
  expect(await screen.findByText(/revision saved/i)).toBeInTheDocument();
  expect(fetcher.mock.calls[6][1].body).toBe('{"expectedVersion":4}');
});

it("requires explicitly discarding edits before reloading a draft", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(draft)));
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  const editor = await screen.findByLabelText("Workflow draft JSON");
  await user.clear(editor);
  await user.paste('{"revision":"local-edit"}');

  expect(screen.getByRole("button", { name: "Load draft" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Discard edits" }));
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(draft.document);
  expect(screen.queryByText("Unsaved changes. Save before validating or creating a revision.")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(/discarded.*saved version is unchanged/i);
  expect(screen.getByRole("button", { name: "Load draft" })).toBeEnabled();
});

it("reconciles an uncertain save by reloading without retrying the write", async () => {
  const edited = '{"revision":"possibly-saved"}';
  const serverDocument = '{"revision":"saved-on-server"}';
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockRejectedValueOnce(new Error("connection lost"))
    .mockResolvedValueOnce(json({ workflowId: id, document: serverDocument, version: 4 }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  const editor = await screen.findByLabelText("Workflow draft JSON");
  await user.clear(editor);
  await user.paste(edited);
  await user.click(screen.getByRole("button", { name: "Save draft" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/may have been saved/i);
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(edited);
  await user.click(screen.getByRole("button", { name: "Reload saved draft" }));
  expect(await screen.findByLabelText("Workflow draft JSON")).toHaveValue(serverDocument);
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(1);
});

it("keeps edits after a draft save conflict and requires reloading server state", async () => {
  const edited = '{"revision":"local-edit"}';
  const serverDocument = '{"revision":"server-edit"}';
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(new Response("", { status: 409 }))
    .mockResolvedValueOnce(json({ workflowId: id, document: serverDocument, version: 4 }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  const editor = await screen.findByLabelText("Workflow draft JSON");
  await user.clear(editor);
  await user.paste(edited);
  await user.click(screen.getByRole("button", { name: "Save draft" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/reload/i);
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(edited);
  expect(screen.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Create immutable revision" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Reload saved draft" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "Reload saved draft" }));
  expect(await screen.findByLabelText("Workflow draft JSON")).toHaveValue(serverDocument);
  expect(screen.getByText("4", { exact: true })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Validate saved draft" })).toBeEnabled();
});

it("disables creation when validation reports issues", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({
      workflowId: id, draftVersion: 3, isValid: false,
      issues: [{ code: "MISSING_REQUIRED_INPUT", message: "Input is required", nodeId: "n1" }],
    })));
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await user.click(await screen.findByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByText(/Input is required/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create immutable revision" })).toBeDisabled();
});

it("retains the draft and prevents another request after an uncertain revision result", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, draftVersion: 3, isValid: true, issues: [] }))
    .mockResolvedValueOnce(json(session))
    .mockRejectedValueOnce(new Error("lost"));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await user.click(await screen.findByRole("button", { name: "Validate saved draft" }));
  await user.click(await screen.findByRole("button", { name: "Create immutable revision" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/may have been created/i);
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(draft.document);
  expect(screen.getByRole("button", { name: "Create immutable revision" })).toBeDisabled();
  expect(fetcher).toHaveBeenCalledTimes(5);
});

it("clears draft contents on authorization loss", async () => {
  const onDenied = vi.fn();
  localStorage.setItem(pendingKey, JSON.stringify({ workflowId: id, expectedVersion: 3 }));
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(new Response("", { status: 401 })));
  render(<WorkflowDraftPanel onDenied={onDenied} />);
  const user = userEvent.setup();
  expect(screen.getByLabelText("Workflow ID")).toHaveValue(id);
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Reload saved draft" }));
  await user.click(await screen.findByRole("button", { name: "Validate saved draft" }));
  await waitFor(() => expect(onDenied).toHaveBeenCalledTimes(1));
  expect(screen.queryByLabelText("Workflow draft JSON")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Workflow ID")).toHaveValue("");
  expect(localStorage.getItem(pendingKey)).toBeNull();
});

it("preserves the draft on a version conflict and requires a reload", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(new Response("", { status: 409 })));
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await user.click(await screen.findByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/reload/i);
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(draft.document);
  expect(screen.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
});

it("restores an uncertain revision workflow after the panel is remounted", async () => {
  localStorage.setItem(pendingKey, JSON.stringify({ workflowId: id, expectedVersion: 3 }));
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, draftVersion: 3, isValid: true, issues: [] })));
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);

  expect(screen.getByLabelText("Workflow ID")).toHaveValue(id);
  expect(screen.getByRole("alert")).toHaveTextContent(/previous revision attempt.*may have been created/i);
  expect(localStorage.getItem(pendingKey)).not.toContain(draft.document);

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Reload saved draft" }));
  expect(await screen.findByLabelText("Workflow draft JSON")).toHaveValue(draft.document);
  await user.click(screen.getByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByText(/valid for version 3/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create immutable revision" })).toBeDisabled();
});
