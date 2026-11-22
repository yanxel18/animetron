import { render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WorkflowDraftPanel } from "./WorkflowDraftPanel";
import { WorkflowNodeOrder } from "./WorkflowNodeOrder";
import { appendWorkflowEdge, appendWorkflowNode, moveWorkflowNode, readWorkflowEdges, readWorkflowNodeOrder, readWorkflowNodeSource, removeWorkflowEdge, removeWorkflowNode, replaceWorkflowNode } from "./workflow-draft-document";

const id = "12345678-1234-4234-8234-123456789abc";
const pendingKey = "animetron.workflow-revision.pending.v1";
const creationKey = "animetron.workflow-draft-creation.pending.v1";
const json = (value: unknown) => new Response(JSON.stringify(value));
const session = { role: "owner", csrfToken: "test-csrf" };
const draft = { workflowId: id, version: 3, document: '{"revision":"r1"}' };
it("replaces only a selected node while preserving node identity and other JSON", () => {
  const node = '{"id":"a","type":"x","config":{"n":1}}';
  const document = `{"schemaVersion":1,"revision":"r1","nodes":[${node}],"edges":[],"n":9007199254740993}`;
  const replacement = '{"id":"a","type":"x","config":{"n":9007199254740995}}';
  expect(replaceWorkflowNode(document, "a", replacement)).toBe(document.replace(node, replacement));
  expect(replaceWorkflowNode(document, "a", replacement.replace('"id":"a"', '"id":"b"'))).toBeNull();
  expect(replaceWorkflowNode(document, "a", `${replacement}],"injected":[1`)).toBeNull();
  expect(replaceWorkflowNode(document, "a", '{"id":"a","id":"a","type":"x","config":{}}')).toBeNull();
  expect(replaceWorkflowNode(document, "missing", replacement)).toBeNull();
});
it("reads a node's exact JSON without rounding numeric values", () => {
  const node = '{ "id":"a", "type":"x", "config":{"n":9007199254740993} }';
  const document = `{"schemaVersion":1,"revision":"r1","nodes":[${node}],"edges":[]}`;
  expect(readWorkflowNodeSource(document, "a")).toBe(node);
  expect(readWorkflowNodeSource(document, "missing")).toBeNull();
  expect(readWorkflowNodeSource(document.replace('"id":"a"', '"id":"a","id":"b"'), "a")).toBeNull();
});
it("inspects a node as exact text and clears its inspector after removal", async () => {
  const node = '{"id":"a","type":"x","config":{"n":9007199254740993,"text":"<script>test</script>"}}';
  const initial = `{"schemaVersion":1,"revision":"r1","nodes":[${node}],"edges":[]}`;
  function Harness() {
    const [value, setValue] = useState(initial);
    return <WorkflowNodeOrder document={value} disabled={false} onDocumentChange={setValue} />;
  }
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Inspect a" }));
  expect(screen.getByLabelText("Selected node JSON")).toHaveTextContent(node);
  expect(screen.getByRole("button", { name: "Inspect a" })).toHaveAttribute("aria-pressed", "true");
  await user.click(screen.getByRole("button", { name: "Remove a" }));
  expect(screen.queryByLabelText("Selected node JSON")).not.toBeInTheDocument();
});
it("edits a selected node locally and rejects an ID change", async () => {
  const initial = '{"schemaVersion":1,"revision":"r1","nodes":[{"id":"a","type":"x","config":{}}],"edges":[]}';
  const pending = vi.fn();
  function Harness() {
    const [value, setValue] = useState(initial);
    return <WorkflowNodeOrder document={value} disabled={false} onDocumentChange={setValue} onNodePendingChange={pending} />;
  }
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Edit a" }));
  expect(screen.getByLabelText("Node JSON")).toHaveFocus();
  expect(pending).toHaveBeenLastCalledWith(true);
  const editor = screen.getByLabelText("Node JSON");
  await user.clear(editor);
  expect(pending).toHaveBeenLastCalledWith(true);
  await user.paste('{"id":"b","type":"x","config":{}}');
  await user.click(screen.getByRole("button", { name: "Apply node changes" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/same node id/i);
  await user.clear(editor);
  await user.paste('{"id":"a","type":"x","config":{"text":"updated"}}');
  await user.click(screen.getByRole("button", { name: "Apply node changes" }));
  expect(pending).toHaveBeenLastCalledWith(false);
  expect(screen.getByLabelText("Selected node JSON")).toHaveTextContent('"text":"updated"');
});
it("removes a connection without rewriting the remaining draft", () => {
  const edge = (id: string) => `{"id":"${id}","source":"a","sourcePort":"text","target":"b","targetPort":"text"}`;
  const document = `{"schemaVersion":1,"revision":"r1","nodes":[],"edges":[${edge("a")}, ${edge("b")}, ${edge("c")}],"n":9007199254740993}`;
  for (const [id, ids] of [["a", ["b", "c"]], ["b", ["a", "c"]], ["c", ["a", "b"]]] as const) {
    const updated = removeWorkflowEdge(document, id);
    expect(readWorkflowEdges(updated!)?.map((item) => item.id)).toEqual(ids);
    expect(updated).toContain('"n":9007199254740993');
  }
  const single = document.replace(`${edge("a")}, ${edge("b")}, ${edge("c")}`, edge("a"));
  expect(readWorkflowEdges(removeWorkflowEdge(single, "a")!)).toEqual([]);
  expect(removeWorkflowEdge(document, "missing")).toBeNull();
  expect(removeWorkflowEdge(document.replace(edge("c"), edge("a")), "a")).toBeNull();
  expect(removeWorkflowEdge(document.replace(edge("c"), '{}'), "a")).toBeNull();
});
it("removes an unconnected node without rewriting unrelated JSON", () => {
  const a = '{"id":"a","type":"sample.constant","config":{}}';
  const b = '{"id":"b","type":"sample.constant","config":{}}';
  const c = '{"id":"c","type":"sample.constant","config":{}}';
  const document = `{"schemaVersion":1,"revision":"r1","nodes":[${a}, ${b}, ${c}],"edges":[],"n":9007199254740993}`;
  for (const [id, ids] of [["a", ["b", "c"]], ["b", ["a", "c"]], ["c", ["a", "b"]]] as const) {
    const updated = removeWorkflowNode(document, id);
    expect(readWorkflowNodeOrder(updated!)).toEqual(ids.map((id) => ({ id, type: "sample.constant" })));
    expect(updated).toContain('"n":9007199254740993');
  }
  const single = document.replace(`${a}, ${b}, ${c}`, a);
  expect(readWorkflowNodeOrder(removeWorkflowNode(single, "a")!)).toEqual([]);
  const connected = document.replace('"edges":[]', '"edges":[{"id":"e","source":"a","sourcePort":"text","target":"b","targetPort":"text"}]');
  expect(removeWorkflowNode(connected, "a")).toBeNull();
  expect(removeWorkflowNode(connected, "b")).toBeNull();
  expect(removeWorkflowNode(document.replace('"edges":[]', '"edges":[{}]'), "a")).toBeNull();
  expect(removeWorkflowNode(document, "missing")).toBeNull();
});
it("appends a connection without changing other JSON or allowing ambiguous IDs", () => {
  const document = '{"schemaVersion":1,"revision":"r1","nodes":[],"edges":[],"large":9007199254740993}';
  const edge = '{"id":"e1","source":"a","sourcePort":"text","target":"b","targetPort":"text"}';
  const updated = appendWorkflowEdge(document, edge);
  expect(updated).toBe(document.replace('"edges":[]', `"edges":[${edge}]`));
  expect(appendWorkflowEdge(updated!, edge)).toBeNull();
  expect(appendWorkflowEdge(document, '{"id":"x","id":"y","source":"a"}')).toBeNull();
  expect(appendWorkflowEdge(document, '{"id":"x"}')).toBeNull();
});
it("appends a node without altering existing JSON values or accepting duplicate IDs", () => {
  const empty = '{"schemaVersion":1,"revision":"r1","nodes":[],"edges":[],"large":9007199254740993}';
  const node = '{"id":"a","type":"sample.constant","config":{"text":"hi"}}';
  const one = appendWorkflowNode(empty, node);
  expect(one).toBe(empty.replace('"nodes":[]', `"nodes":[${node}]`));
  expect(appendWorkflowNode(one!, node)).toBeNull();
  const two = appendWorkflowNode(one!, '{"id":"b","type":"sample.constant","config":{"text":"bye"}}');
  expect(two).toContain('"large":9007199254740993');
  expect(readWorkflowNodeOrder(two!)).toEqual([{ id: "a", type: "sample.constant" }, { id: "b", type: "sample.constant" }]);
  expect(appendWorkflowNode(empty, '{"id":"a","id":"b","type":"x","config":{}}')).toBeNull();
  expect(appendWorkflowNode(empty, '{"id":"a"}')).toBeNull();
  expect(appendWorkflowNode(empty, `${node}],"injected":[1`)).toBeNull();
});
it("adds a supplied node locally and reports invalid input", async () => {
  const document = '{"schemaVersion":1,"revision":"r1","nodes":[],"edges":[]}';
  const onChange = vi.fn();
  render(<WorkflowNodeOrder document={document} disabled={false} onDocumentChange={onChange} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Node JSON"), "invalid");
  await user.click(screen.getByRole("button", { name: "Add node" }));
  expect(screen.getByRole("alert")).toHaveTextContent(/cannot add/i);
  expect(onChange).not.toHaveBeenCalled();
  await user.clear(screen.getByLabelText("Node JSON"));
  await user.paste('{"id":"a","type":"sample.constant","config":{"text":"hi"}}');
  await user.click(screen.getByRole("button", { name: "Add node" }));
  expect(onChange).toHaveBeenCalledOnce();
  expect(readWorkflowNodeOrder(onChange.mock.calls[0][0])).toEqual([{ id: "a", type: "sample.constant" }]);
});
it("adds a connection locally from named fields", async () => {
  const document = '{"schemaVersion":1,"revision":"r1","nodes":[],"edges":[]}';
  const onChange = vi.fn();
  render(<WorkflowNodeOrder document={document} disabled={false} onDocumentChange={onChange} />);
  const user = userEvent.setup();
  for (const [label, value] of [["Connection ID", "e1"], ["Source node ID", "a"], ["Source port", "text"], ["Target node ID", "b"], ["Target port", "text"]]) {
    await user.type(screen.getByLabelText(label), value);
  }
  await user.click(screen.getByRole("button", { name: "Add connection" }));
  expect(onChange).toHaveBeenCalledOnce();
  expect(JSON.parse(onChange.mock.calls[0][0]).edges).toEqual([{ id: "e1", source: "a", sourcePort: "text", target: "b", targetPort: "text" }]);
});
it("removes a node locally and keeps keyboard focus in the node section", async () => {
  const document = '{"schemaVersion":1,"revision":"r1","nodes":[{"id":"a","type":"sample.constant","config":{}}],"edges":[]}';
  const user = userEvent.setup();
  function Harness() {
    const [value, setValue] = useState(document);
    return <WorkflowNodeOrder document={value} disabled={false} onDocumentChange={setValue} />;
  }
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Remove a" }));
  expect(screen.getByRole("heading", { name: "Node order" })).toHaveFocus();
  expect(screen.getByRole("status")).toHaveTextContent(/removed a locally/i);
  expect(screen.getByText(/no nodes to reorder/i)).toBeInTheDocument();
});
it("removes a connection locally and allows the previously connected node to be removed", async () => {
  const document = '{"schemaVersion":1,"revision":"r1","nodes":[{"id":"a","type":"sample.constant","config":{}}],"edges":[{"id":"e","source":"a","sourcePort":"text","target":"b","targetPort":"text"}]}';
  const user = userEvent.setup();
  function Harness() {
    const [value, setValue] = useState(document);
    return <WorkflowNodeOrder document={value} disabled={false} onDocumentChange={setValue} />;
  }
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Remove connection e" }));
  expect(screen.getByRole("heading", { name: "Connections" })).toHaveFocus();
  expect(screen.getByRole("status")).toHaveTextContent(/removed connection e locally/i);
  await user.click(screen.getByRole("button", { name: "Remove a" }));
  expect(screen.getByText(/no nodes to reorder/i)).toBeInTheDocument();
});
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

it("warns on browser unload only while the draft document has unsaved changes", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(draft)));
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  const editor = await screen.findByLabelText("Workflow draft JSON");
  const clean = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);
  await user.type(editor, "x");
  const dirty = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(dirty);
  expect(dirty.defaultPrevented).toBe(true);
  await user.click(screen.getByRole("button", { name: "Discard edits" }));
  const discarded = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(discarded);
  expect(discarded.defaultPrevented).toBe(false);
});

it("protects partially entered node and connection fields until added or cleared", async () => {
  const document = '{"schemaVersion":1,"revision":"r1","nodes":[],"edges":[]}';
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ ...draft, document })));
  render(<WorkflowDraftPanel onDenied={vi.fn()} />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await screen.findByLabelText("Workflow draft JSON");
  await user.type(screen.getByLabelText("Node JSON"), "partial");
  expect(screen.getByLabelText("Workflow ID")).toBeDisabled();
  expect(screen.getByLabelText("Workflow draft JSON")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Validate saved draft" })).toBeDisabled();
  const nodeUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(nodeUnload);
  expect(nodeUnload.defaultPrevented).toBe(true);
  await user.click(screen.getByRole("button", { name: "Clear node input" }));
  expect(screen.getByLabelText("Workflow draft JSON")).toBeEnabled();
  await user.type(screen.getByLabelText("Source node ID"), "unfinished");
  expect(screen.getByRole("button", { name: "Load draft" })).toBeDisabled();
  const edgeUnload = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(edgeUnload);
  expect(edgeUnload.defaultPrevented).toBe(true);
  await user.click(screen.getByRole("button", { name: "Clear connection input" }));
  expect(screen.getByRole("button", { name: "Validate saved draft" })).toBeEnabled();
  const clean = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);
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
