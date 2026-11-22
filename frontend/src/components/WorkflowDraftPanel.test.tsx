import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WorkflowDraftPanel } from "./WorkflowDraftPanel";
import { moveWorkflowNode, readWorkflowNodeOrder } from "./workflow-draft-document";

const id = "12345678-1234-4234-8234-123456789abc";
const pendingKey = "animetron.workflow-revision.pending.v1";
const creationKey = "animetron.workflow-draft-creation.pending.v1";
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
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.removeItem(pendingKey);
  localStorage.removeItem(creationKey);
  Reflect.deleteProperty(navigator, "locks");
});

it("generates a workflow ID only on explicit request", async () => {
  const generate = vi.spyOn(crypto, "randomUUID").mockReturnValue(id);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  expect(generate).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Generate workflow ID" }));
  expect(screen.getByLabelText("New workflow ID")).toHaveValue(id);
  expect(generate).toHaveBeenCalledTimes(1);
});

it("keeps manual ID entry available when secure UUID generation is unavailable", () => {
  vi.stubGlobal("crypto", {});
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Generate workflow ID" })).toBeDisabled();
  expect(screen.getByLabelText("New workflow ID")).toBeEnabled();
  expect(screen.getByText(/secure ID generation is unavailable/i)).toBeInTheDocument();
});

it("reports a generator failure without replacing the entered ID", async () => {
  vi.spyOn(crypto, "randomUUID").mockImplementation(() => { throw new Error("unavailable"); });
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("New workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Generate workflow ID" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/could not be generated/i);
  expect(screen.getByLabelText("New workflow ID")).toHaveValue(id);
});

it("creates an empty draft for an explicit ID without starting a workflow", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ workflowId: id, document: "", version: 1 }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("New workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Create empty draft" }));
  expect(await screen.findByText(/empty draft created/i)).toHaveTextContent(id);
  expect(localStorage.getItem(creationKey)).toBe(id);
  await user.click(screen.getByRole("button", { name: "I recorded this ID" }));
  expect(localStorage.getItem(creationKey)).toBeNull();
  expect(fetcher.mock.calls[1][1].body).toBe('{"document":"","expectedVersion":null}');
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("restores an uncertain creation after reload and only retries the same ID after a read", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(session))
    .mockRejectedValueOnce(new Error("lost response"))
    .mockResolvedValueOnce(new Response("", { status: 404 }))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(new Response("", { status: 409 }))
    .mockResolvedValueOnce(json({ workflowId: id, document: "other document", version: 2 }));
  vi.stubGlobal("fetch", fetcher);
  const { unmount } = render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("New workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Create empty draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/may have been created/i);
  unmount();

  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  expect(screen.getByLabelText("New workflow ID")).toHaveValue(id);
  expect(screen.getByLabelText("New workflow ID")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Generate workflow ID" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Create empty draft" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Check draft creation" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/not found.*same id/i);
  await user.click(screen.getByRole("button", { name: "Create empty draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/check.*same id/i);
  await user.click(screen.getByRole("button", { name: "Check draft creation" }));
  expect(await screen.findByText(/draft found/i)).toHaveTextContent(id);
  expect(localStorage.getItem(creationKey)).toBe(id);
  await user.click(screen.getByRole("button", { name: "I recorded this ID" }));
  expect(localStorage.getItem(creationKey)).toBeNull();
  expect(fetcher.mock.calls.filter((call) => call[1]?.method === "PUT")).toHaveLength(2);
});

it("preserves revision recovery when draft creation is denied", async () => {
  const marker = JSON.stringify({ workflowId: id, expectedVersion: 3 });
  localStorage.setItem(pendingKey, marker);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ role: "viewer", csrfToken: "test-csrf" })));
  const onDenied = vi.fn();
  render(<WorkflowDraftPanel onDenied={onDenied} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("New workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Create empty draft" }));
  await waitFor(() => expect(onDenied).toHaveBeenCalledTimes(1));
  expect(localStorage.getItem(pendingKey)).toBe(marker);
});

it("blocks draft creation while there are unsaved edits and editing during creation", async () => {
  let finish: (value: Response) => void = () => { throw new Error("request not started"); };
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json(draft))
    .mockResolvedValueOnce(json(session))
    .mockReturnValueOnce(pending);
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  const editor = await screen.findByLabelText("Workflow draft JSON");
  await user.clear(editor);
  await user.paste("unsaved");
  expect(screen.getByRole("button", { name: "Create empty draft" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Generate workflow ID" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Discard edits" }));
  await user.type(screen.getByLabelText("New workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Create empty draft" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(editor).toBeDisabled();
  finish(new Response("", { status: 403 }));
  await waitFor(() => expect(screen.queryByLabelText("Workflow draft JSON")).not.toBeInTheDocument());
});

it("initializes an empty saved draft locally and saves only on request", async () => {
  const empty = { ...draft, document: "" };
  const initialized = '{\n  "schemaVersion": 1,\n  "revision": "draft",\n  "nodes": [],\n  "edges": []\n}';
  const fetcher = vi.fn().mockResolvedValueOnce(json(empty))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ ...empty, document: initialized, version: 4 }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await screen.findByLabelText("Workflow draft JSON");
  await user.click(screen.getByRole("button", { name: "Initialize empty draft" }));
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(initialized);
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveFocus();
  expect(screen.queryByRole("button", { name: "Initialize empty draft" })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Discard edits" }));
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "Initialize empty draft" }));
  await user.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({ document: initialized, expectedVersion: 3 });
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
  expect(screen.queryByRole("list", { name: "Workflow node order" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Validate saved draft" }));
  expect(await screen.findByText(/valid for version 3/i)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Create immutable revision" }));
  expect(await screen.findByText(/revision saved/i)).toBeInTheDocument();
  expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
  expect(screen.getByLabelText("Created revision canonical JSON")).toHaveTextContent("{}");
  expect(fetcher.mock.calls[4][1].body).toBe('{"expectedVersion":3}');
});

it("reorders a loaded draft node with the keyboard and saves the unchanged graph", async () => {
  const document = JSON.stringify({
    schemaVersion: 1,
    revision: "r1",
    nodes: [
      { id: "node-a", type: "sample.constant", config: { value: "A", options: [1, 2] } },
      { id: "node-b", type: "sample.constant", config: { value: "B" } },
    ],
    edges: [{
      id: "edge-a-b", source: "node-a", sourcePort: "value",
      target: "node-b", targetPort: "value",
    }],
  });
  const parsed = JSON.parse(document) as {
    schemaVersion: number;
    revision: string;
    nodes: { id: string; type: string; config: Record<string, unknown> }[];
    edges: unknown[];
  };
  const reorderedDocument = JSON.stringify({
    ...parsed,
    nodes: [parsed.nodes[1], parsed.nodes[0]],
  });
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json({ ...draft, document }))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ ...draft, document: reorderedDocument, version: 4 }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));

  const moveUp = await screen.findByRole("button", { name: "Move node-b up" });
  moveUp.focus();
  await user.keyboard("{Enter}");

  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(reorderedDocument);
  expect(screen.getByRole("button", { name: "Move node-b up" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Move node-b down" })).toHaveFocus();
  expect(screen.getByRole("button", { name: "Move node-a up" })).toBeEnabled();
  expect(screen.getByText(/unsaved changes/i)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText(/saved as version 4/i)).toBeInTheDocument();
  expect(fetcher.mock.calls[2][1].body).toBe(
    JSON.stringify({ document: reorderedDocument, expectedVersion: 3 }),
  );
});

it("keeps duplicate-key drafts editable without offering lossy node reordering", async () => {
  const document = '{"schemaVersion":1,"revision":"r1","nodes":[],"nodes":[],"edges":[]}';
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ ...draft, document })));
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));

  expect(await screen.findByLabelText("Workflow draft JSON")).toHaveValue(document);
  expect(screen.queryByRole("list", { name: "Workflow node order" })).not.toBeInTheDocument();
  expect(screen.getByRole("note")).toHaveTextContent(/does not contain a readable workflow node list/i);
});

it("preserves exact JSON values and unrelated text when reordering and saving", async () => {
  const first = '{"id":"node-a","type":"sample.constant","config":{"n":9007199254740993,"negativeZero":-0,"exp":1e400}}';
  const second = '{"id":"node-b","type":"sample.constant","config":{"text":"}, [\\\\\\""}}';
  const prefix = '{ "schemaVersion": 1, "revision":"r1", "extra":9007199254740993, "nodes":[ ';
  const separator = ',\n    ';
  const suffix = ' ],"edges":[] }';
  const document = `${prefix}${first}${separator}${second}${suffix}`;
  const expected = `${prefix}${second}${separator}${first}${suffix}`;
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json({ ...draft, document }))
    .mockResolvedValueOnce(json(session))
    .mockResolvedValueOnce(json({ ...draft, document: expected, version: 4 }));
  vi.stubGlobal("fetch", fetcher);
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await user.click(await screen.findByRole("button", { name: "Move node-b up" }));
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue(expected);
  await user.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByText(/saved as version 4/i)).toBeInTheDocument();
  expect(fetcher.mock.calls[2][1].body).toBe(
    JSON.stringify({ document: expected, expectedVersion: 3 }),
  );
});

it("reorders only top-level nodes despite nested node arrays and escaped keys", () => {
  const a = '{"id":"a","type":"t","config":{"nodes":[{"x":1}]}}';
  const b = '{"id":"b","type":"t","config":{"nested":[[],{"nodes":[2,3]}]}}';
  const c = '{"id":"c","type":"t","config":{}}';
  const prefix = '{"schemaVersion":1,"revision":"r1","metadata":{"nodes":[0]},"no\\u0064es":[';
  const suffix = '],"edges":[]}';
  const document = `${prefix}${a}, ${b},\n${c}${suffix}`;
  const moved = `${prefix}${a}, ${c},\n${b}${suffix}`;
  expect(moveWorkflowNode(document, "b", "down")).toBe(moved);
  expect(moveWorkflowNode(moved, "b", "up")).toBe(document);
  expect(readWorkflowNodeOrder(document.replace('"edges":[]', '"edges":[],"e\\u0064ges":[]'))).toBeNull();
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
