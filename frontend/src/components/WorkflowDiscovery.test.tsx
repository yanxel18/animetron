import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { WorkflowDiscovery } from "./WorkflowDiscovery";

const id = "12345678-1234-4234-8234-123456789abc";
afterEach(() => vi.unstubAllGlobals());

it("loads node validation metadata on request without claiming readiness", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.endsWith("/node-types") ? { scope: "sample-validation", nodes: [{ type: "sample.constant", inputs: [], outputs: [{ name: "text", type: "text", required: false }], configSchema: { type: "object" } }] } : { data: [], nextCursor: null },
  )))));
  render(<WorkflowDiscovery />);
  await userEvent.click(screen.getByRole("button", { name: "Load sample node types" }));
  expect(await screen.findByText("sample.constant")).toBeInTheDocument();
  expect(screen.getByText(/does not establish execution or model readiness/i)).toBeInTheDocument();
  expect(screen.getByLabelText("Configuration schema for sample.constant")).toHaveTextContent('"type": "object"');
});

it("clears protected workflow state when the node catalog denies access", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(
    url.endsWith("/node-types") ? new Response("", { status: 403 }) :
      new Response(JSON.stringify({ data: [{ workflowId: id }], nextCursor: null })),
  )));
  render(<WorkflowDiscovery />);
  await screen.findByRole("button", { name: new RegExp(id) });
  await userEvent.click(screen.getByRole("button", { name: "Load sample node types" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/access/i));
  expect(screen.queryByText(id)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /retry/i })).toHaveFocus();
});

it("offers a retry when the node catalog is unavailable", async () => {
  let attempts = 0;
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(
    url.endsWith("/node-types") ? (++attempts === 1 ? new Response("", { status: 503 }) :
      new Response(JSON.stringify({ scope: "sample-validation", nodes: [] }))) :
      new Response(JSON.stringify({ data: [], nextCursor: null })),
  )));
  render(<WorkflowDiscovery />);
  await userEvent.click(screen.getByRole("button", { name: "Load sample node types" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("503");
  await userEvent.click(screen.getByRole("button", { name: "Reload sample node types" }));
  expect(await screen.findByText("No sample node types are available.")).toBeInTheDocument();
});

it("browses saved revisions without offering write actions", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.includes("/revisions")
      ? { data: [{ workflowId: id, revision: "rev-1", createdAt: "2025-01-02T00:00:00Z" }], nextCursor: null }
      : { data: [{ workflowId: id }], nextCursor: null },
  )))));
  render(<WorkflowDiscovery />);
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(id) }));
  expect(await screen.findByRole("button", { name: "Inspect rev-1" })).toBeInTheDocument();
  expect(screen.getByText(/read-only/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /edit|run|publish/i })).not.toBeInTheDocument();
});

it("clears all protected content after a revision request is forbidden", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(
    url.includes("/revisions") ? new Response("", { status: 403 }) :
      new Response(JSON.stringify({ data: [{ workflowId: id }], nextCursor: null })),
  )));
  render(<WorkflowDiscovery />);
  await userEvent.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/access/i));
  expect(screen.queryByText(id)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /retry/i })).toHaveFocus();
});

it("ignores an obsolete revision response after another workflow is selected", async () => {
  const second = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  let resolveFirst!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (!url.includes("/revisions")) return Promise.resolve(new Response(JSON.stringify({
      data: [{ workflowId: id }, { workflowId: second }], nextCursor: null,
    })));
    if (url.includes(id)) return new Promise<Response>((resolve) => { resolveFirst = resolve; });
    return Promise.resolve(new Response(JSON.stringify({
      data: [{ workflowId: second, revision: "new", createdAt: "2025-01-02T00:00:00Z" }], nextCursor: null,
    })));
  }));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(screen.getByRole("button", { name: new RegExp(second) }));
  expect(await screen.findByRole("button", { name: "Inspect new" })).toBeInTheDocument();
  resolveFirst(new Response(JSON.stringify({
    data: [{ workflowId: id, revision: "obsolete", createdAt: "2025-01-02T00:00:00Z" }], nextCursor: null,
  })));
  await waitFor(() => expect(screen.queryByText("obsolete")).not.toBeInTheDocument());
});

it("pages revision metadata with an opaque cursor and clears it on a 401", async () => {
  const first = Array.from({ length: 50 }, (_, index) => ({
    workflowId: id, revision: `revision-${index}`, createdAt: "2025-01-02T00:00:00Z",
  }));
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (!url.includes("/revisions")) return Promise.resolve(new Response(JSON.stringify({
      data: [{ workflowId: id }], nextCursor: null,
    })));
    if (url.includes("cursor=")) return Promise.resolve(new Response("", { status: 401 }));
    return Promise.resolve(new Response(JSON.stringify({ data: first, nextCursor: "revision_cursor" })));
  }));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(await screen.findByRole("button", { name: "Next revisions" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/access/i));
  expect(screen.queryByText("revision-0")).not.toBeInTheDocument();
  expect(screen.queryByText(id)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/api/v1/auth/login");
});

it("inspects exact inert canonical text and the returned digest", async () => {
  const canonicalJson = '{"payload":"<script>evil()</script>","escaped":"\\\\u96ea"}';
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.includes("/revision?") ? { workflowId: id, revision: "../雪", canonicalJson, sha256: "b".repeat(64) } :
    url.includes("/revisions") ? { data: [{ workflowId: id, revision: "../雪", createdAt: "2025-01-02T00:00:00Z" }], nextCursor: null } :
    { data: [{ workflowId: id }], nextCursor: null },
  )))));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(await screen.findByRole("button", { name: /inspect.*\.\.\/雪/i }));
  expect(await screen.findByText(canonicalJson)).toBeInTheDocument();
  expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByText(/immutable.*read-only/i)).toBeInTheDocument();
});

it("drops obsolete detail responses and clears detail on forbidden access", async () => {
  let resolveFirst!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.includes("/revision?")) {
      if (new URL(url, "http://localhost").searchParams.get("revision") === "first")
        return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      return Promise.resolve(new Response("", { status: 403 }));
    }
    return Promise.resolve(new Response(JSON.stringify(url.includes("/revisions")
      ? { data: ["first", "second"].map((revision) => ({ workflowId: id, revision, createdAt: "2025-01-02T00:00:00Z" })), nextCursor: null }
      : { data: [{ workflowId: id }], nextCursor: null })));
  }));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(await screen.findByRole("button", { name: /inspect first/i }));
  await user.click(screen.getByRole("button", { name: /inspect second/i }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/access/i));
  await act(async () => resolveFirst(new Response(JSON.stringify({ workflowId: id, revision: "first", canonicalJson: '{"private":true}', sha256: "a".repeat(64) }))));
  await waitFor(() => expect(screen.queryByText('{"private":true}')).not.toBeInTheDocument());
  expect(screen.queryByText(id)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toHaveFocus();
});

it("keeps the newest detail when an earlier request resolves late", async () => {
  let resolveFirst!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.includes("/revision?")) {
      if (new URL(url, "http://localhost").searchParams.get("revision") === "first")
        return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      return Promise.resolve(new Response(JSON.stringify({ workflowId: id, revision: "second", canonicalJson: '{"new":true}', sha256: "b".repeat(64) })));
    }
    return Promise.resolve(new Response(JSON.stringify(url.includes("/revisions")
      ? { data: ["first", "second"].map((revision) => ({ workflowId: id, revision, createdAt: "2025-01-02T00:00:00Z" })), nextCursor: null }
      : { data: [{ workflowId: id }], nextCursor: null })));
  }));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(await screen.findByRole("button", { name: "Inspect first" }));
  await user.click(screen.getByRole("button", { name: "Inspect second" }));
  expect(await screen.findByText('{"new":true}')).toBeInTheDocument();
  await act(async () => resolveFirst(new Response(JSON.stringify({ workflowId: id, revision: "first", canonicalJson: '{"old":true}', sha256: "a".repeat(64) }))));
  expect(screen.queryByText('{"old":true}')).not.toBeInTheDocument();
  expect(screen.getByText('{"new":true}')).toBeInTheDocument();
});

it("shows a detail error and retries the same revision", async () => {
  let failed = false;
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.includes("/revision?")) {
      if (!failed) { failed = true; return Promise.resolve(new Response("", { status: 503 })); }
      return Promise.resolve(new Response(JSON.stringify({ workflowId: id, revision: "r", canonicalJson: "{}", sha256: "a".repeat(64) })));
    }
    return Promise.resolve(new Response(JSON.stringify(url.includes("/revisions")
      ? { data: [{ workflowId: id, revision: "r", createdAt: "2025-01-02T00:00:00Z" }], nextCursor: null }
      : { data: [{ workflowId: id }], nextCursor: null })));
  }));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(await screen.findByRole("button", { name: /inspect r/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent("503");
  await user.click(screen.getByRole("button", { name: "Retry revision" }));
  expect(screen.getByRole("heading", { name: "Revision inspector" })).toHaveFocus();
  expect(await screen.findByText("{}")).toBeInTheDocument();
});

it("clears a previously displayed revision on 401 for another selection", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.includes("/revision?")) {
      return Promise.resolve(new URL(url, "http://localhost").searchParams.get("revision") === "first"
        ? new Response(JSON.stringify({ workflowId: id, revision: "first", canonicalJson: '{"private":true}', sha256: "a".repeat(64) }))
        : new Response("", { status: 401 }));
    }
    return Promise.resolve(new Response(JSON.stringify(url.includes("/revisions")
      ? { data: ["first", "second"].map((revision) => ({ workflowId: id, revision, createdAt: "2025-01-02T00:00:00Z" })), nextCursor: null }
      : { data: [{ workflowId: id }], nextCursor: null })));
  }));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: new RegExp(id) }));
  await user.click(await screen.findByRole("button", { name: "Inspect first" }));
  expect(await screen.findByText('{"private":true}')).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Inspect second" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/access/i));
  expect(screen.queryByText('{"private":true}')).not.toBeInTheDocument();
  expect(screen.queryByText(id)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
});

it("clears loaded draft data when discovery loses authorization", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
    if (url.endsWith("/draft")) return Promise.resolve(new Response(JSON.stringify({
      workflowId: id, version: 1, document: '{"private":"draft"}',
    })));
    if (url.includes("/revisions")) return Promise.resolve(new Response("", { status: 403 }));
    return Promise.resolve(new Response(JSON.stringify({ data: [{ workflowId: id }], nextCursor: null })));
  }));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  expect(await screen.findByText('{"private":"draft"}')).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: id }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/access/i));
  expect(screen.queryByText('{"private":"draft"}')).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Workflow ID")).not.toBeInTheDocument();
});

it("clears discovery data when a draft request loses authorization", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(
    url.endsWith("/draft") ? new Response("", { status: 401 }) :
      new Response(JSON.stringify({ data: [{ workflowId: id }], nextCursor: null })),
  )));
  render(<WorkflowDiscovery />);
  const user = userEvent.setup();
  await screen.findByRole("button", { name: id });
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/access/i));
  expect(screen.queryByRole("button", { name: id })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Workflow ID")).not.toBeInTheDocument();
});
