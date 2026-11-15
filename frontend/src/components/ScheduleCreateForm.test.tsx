import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SCHEDULE_CREATE_PENDING_KEY } from "../api/schedule-create";
import { ScheduleCreateForm } from "./ScheduleCreateForm";

const workflowId = "3986b877-6311-4193-9a9e-30788e8c8787";
const revision = "release/α<&>";
const descriptor = {
  id: "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53",
  workflowId,
  revision,
  expression: "0 9 * * *",
  timeZone: "Asia/Tokyo",
  enabled: false,
  nextDueAt: null,
  overlapPolicy: "skip",
  missedRunPolicy: "skip",
  version: 1,
  createdAt: "2026-11-15T00:00:00Z",
  updatedAt: "2026-11-15T00:00:00Z",
};

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installLocks() {
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: {
      request: vi.fn(async (_name: string, _options: unknown, callback: (lock: Lock | null) => Promise<unknown>) =>
        callback({ name: "test-lock", mode: "exclusive" } as Lock)),
    },
  });
}

function discoveryFetch(post: () => Promise<Response> | Response = () => response(descriptor, 201)) {
  return vi.fn((url: string, options?: RequestInit) => {
    if (url === "/api/v1/workflows?limit=50") {
      return Promise.resolve(response({ data: [{ workflowId }], nextCursor: null }));
    }
    if (url === `/api/v1/workflows/${workflowId}/revisions?limit=50`) {
      return Promise.resolve(response({
        data: [{ workflowId, revision, createdAt: "2026-11-15T00:00:00Z" }],
        nextCursor: null,
      }));
    }
    if (url === "/api/v1/auth/session") {
      return Promise.resolve(response({ role: "owner", csrfToken: "test-csrf" }));
    }
    if (url === "/api/v1/schedules" && options?.method === "POST") return Promise.resolve(post());
    throw new Error(`Unexpected fixture request: ${String(url)}`);
  });
}

async function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(await screen.findByLabelText("Workflow ID"), workflowId);
  await user.selectOptions(await screen.findByLabelText("Saved revision"), revision);
  await user.type(screen.getByLabelText("Five-field cron expression"), "0 9 * * *");
  await user.clear(screen.getByLabelText("IANA time zone"));
  await user.type(screen.getByLabelText("IANA time zone"), "Asia/Tokyo");
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.removeItem(SCHEDULE_CREATE_PENDING_KEY);
  Reflect.deleteProperty(navigator, "locks");
});

describe("owner-only schedule creation form", () => {
  it("uses only persisted workflow and revision choices, preserving special revision IDs", async () => {
    const user = userEvent.setup();
    installLocks();
    const fetchMock = discoveryFetch();
    vi.stubGlobal("fetch", fetchMock);
    const onCreated = vi.fn();
    render(<ScheduleCreateForm onCreated={onCreated} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);

    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(descriptor));
    const post = fetchMock.mock.calls.find((call) => call[1]?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      workflowId,
      revision,
      expression: "0 9 * * *",
      timeZone: "Asia/Tokyo",
      enabled: false,
      overlapPolicy: "skip",
      missedRunPolicy: "skip",
    });
  });

  it("focuses a linked error summary and keeps field errors after invalid submit", async () => {
    const user = userEvent.setup();
    installLocks();
    vi.stubGlobal("fetch", discoveryFetch());
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Create schedule" }));

    const summary = await screen.findByRole("alert");
    expect(summary).toHaveFocus();
    expect(summary).toHaveTextContent(/choose a persisted workflow/i);
    expect(screen.getAllByText(/choose a persisted workflow/i)).toHaveLength(2);
    expect(screen.getAllByText(/enter a five-field cron expression/i)).toHaveLength(2);
  });

  it("validates the server's Unicode character limits without silently truncating fields", async () => {
    const user = userEvent.setup();
    installLocks();
    const fetchMock = discoveryFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);
    await fillValidForm(user);
    fireEvent.change(screen.getByLabelText("Five-field cron expression"), { target: { value: "x".repeat(257) } });
    fireEvent.change(screen.getByLabelText("IANA time zone"), { target: { value: "Z".repeat(256) } });
    await user.click(screen.getByRole("button", { name: "Create schedule" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/between 1 and 256 characters/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/between 1 and 255 characters/i);
    expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "POST")).toHaveLength(0);
  });

  it("does not render creation fields when persisted workflow access is denied", async () => {
    const onAuthorizationLost = vi.fn();
    installLocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({}, 403)));
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={onAuthorizationLost} onRefresh={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/owner access/i);
    expect(screen.queryByLabelText("Five-field cron expression")).not.toBeInTheDocument();
    expect(onAuthorizationLost).toHaveBeenCalledTimes(1);
  });

  it("prevents a second submit while the non-idempotent POST is in flight", async () => {
    const user = userEvent.setup();
    installLocks();
    let finishPost: (value: Response) => void = () => { throw new Error("Missing POST"); };
    const fetchMock = discoveryFetch(() => new Promise<Response>((resolve) => { finishPost = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);
    await fillValidForm(user);
    const submit = screen.getByRole("button", { name: "Create schedule" });

    await user.click(submit);
    await waitFor(() => expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "POST")).toHaveLength(1));
    expect(submit).toBeDisabled();
    expect(localStorage.getItem(SCHEDULE_CREATE_PENDING_KEY)).toBe("pending");
    finishPost(response(descriptor, 201));
    await waitFor(() => expect(submit).not.toBeDisabled());
  });

  it("keeps a durable unknown marker across unmount and blocks a remounted form", async () => {
    const user = userEvent.setup();
    installLocks();
    let finishPost: (value: Response) => void = () => { throw new Error("Missing POST"); };
    const fetchMock = discoveryFetch(() => new Promise<Response>((resolve) => { finishPost = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const first = render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);
    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Create schedule" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "POST")).toHaveLength(1));

    first.unmount();
    finishPost(response({}, 503));
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);

    expect(await screen.findByText(/a previous creation may have succeeded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start a new attempt" })).toBeDisabled();
    expect(localStorage.getItem(SCHEDULE_CREATE_PENDING_KEY)).toBe("pending");
    expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "POST")).toHaveLength(1);
  });

  it("keeps uncertainty when reviewing the schedule list and requires explicit acknowledgement", async () => {
    const user = userEvent.setup();
    installLocks();
    localStorage.setItem(SCHEDULE_CREATE_PENDING_KEY, "pending");
    const onRefresh = vi.fn();
    vi.stubGlobal("fetch", discoveryFetch());
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={onRefresh} />);

    expect(await screen.findByText(/a previous creation may have succeeded/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh schedules" }));
    expect(onRefresh).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Start a new attempt" })).toBeDisabled();
    expect(localStorage.getItem(SCHEDULE_CREATE_PENDING_KEY)).toBe("pending");
  });

  it("requires explicit duplicate-risk acknowledgement for a new attempt and keeps older uncertainty", async () => {
    const user = userEvent.setup();
    installLocks();
    localStorage.setItem(SCHEDULE_CREATE_PENDING_KEY, "pending");
    const fetchMock = discoveryFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);
    await fillValidForm(user);
    const start = screen.getByRole("button", { name: "Start a new attempt" });
    expect(start).toBeDisabled();
    await user.click(screen.getByLabelText(/I understand the prior attempt may have succeeded/i));
    expect(start).toBeEnabled();
    await user.click(start);

    expect(await screen.findByText(/earlier uncertain attempt remains unresolved/i)).toBeInTheDocument();
    expect(localStorage.getItem(SCHEDULE_CREATE_PENDING_KEY)).toBe("pending");
    expect(screen.getByRole("button", { name: "Start a new attempt" })).toBeDisabled();
  });

  it("ignores a late revision response after the user selects a different workflow", async () => {
    const user = userEvent.setup();
    installLocks();
    const secondWorkflow = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    let finishFirstRevision: (value: Response) => void = () => { throw new Error("Missing first revision response"); };
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/v1/workflows?limit=50") {
        return Promise.resolve(response({ data: [{ workflowId }, { workflowId: secondWorkflow }], nextCursor: null }));
      }
      if (url === `/api/v1/workflows/${workflowId}/revisions?limit=50`) {
        return new Promise<Response>((resolve) => { finishFirstRevision = resolve; });
      }
      if (url === `/api/v1/workflows/${secondWorkflow}/revisions?limit=50`) {
        return Promise.resolve(response({
          data: [{ workflowId: secondWorkflow, revision: "revision-B", createdAt: "2026-11-15T00:00:00Z" }],
          nextCursor: null,
        }));
      }
      throw new Error(`Unexpected fixture request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);
    const workflow = await screen.findByLabelText("Workflow ID");
    await user.selectOptions(workflow, workflowId);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/workflows/${workflowId}/revisions?limit=50`,
      expect.any(Object),
    ));
    await user.selectOptions(workflow, secondWorkflow);
    expect(await screen.findByRole("option", { name: "revision-B" })).toBeInTheDocument();
    finishFirstRevision(response({
      data: [{ workflowId, revision: "revision-A", createdAt: "2026-11-15T00:00:00Z" }],
      nextCursor: null,
    }));

    await waitFor(() => expect(screen.queryByRole("option", { name: "revision-A" })).not.toBeInTheDocument());
    expect(screen.getByRole("option", { name: "revision-B" })).toBeInTheDocument();
  });

  it("focuses deterministic server errors and does not mislabel a conflict as uncertain", async () => {
    const user = userEvent.setup();
    installLocks();
    const fetchMock = discoveryFetch(() => response({}, 409));
    vi.stubGlobal("fetch", fetchMock);
    render(<ScheduleCreateForm onCreated={vi.fn()} onAuthorizationLost={vi.fn()} onRefresh={vi.fn()} />);
    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Create schedule" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveFocus();
    expect(alert).toHaveTextContent(/conflicts with current server state/i);
    expect(screen.queryByText(/outcome is uncertain/i)).not.toBeInTheDocument();
    expect(localStorage.getItem(SCHEDULE_CREATE_PENDING_KEY)).toBeNull();
  });
});
