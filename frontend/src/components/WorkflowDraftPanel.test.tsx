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
  expect(await screen.findByText('{"revision":"r1"}')).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByText(/valid for version 3/i)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Create immutable revision" }));
  expect(await screen.findByText(/revision saved/i)).toBeInTheDocument();
  expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  expect(screen.getByLabelText("Created revision canonical JSON")).toHaveTextContent("{}");
  expect(fetcher.mock.calls[4][1].body).toBe('{"expectedVersion":3}');
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
  expect(screen.getByText('{"revision":"r1"}')).toBeInTheDocument();
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
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await user.click(await screen.findByRole("button", { name: "Validate saved draft" }));
  await waitFor(() => expect(onDenied).toHaveBeenCalledTimes(1));
  expect(screen.queryByText('{"revision":"r1"}')).not.toBeInTheDocument();
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
  expect(screen.getByText(draft.document)).toBeInTheDocument();
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
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  expect(await screen.findByText(draft.document)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByText(/valid for version 3/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create immutable revision" })).toBeDisabled();
});
