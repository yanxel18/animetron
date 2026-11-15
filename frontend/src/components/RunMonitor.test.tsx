import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunEventPageOutput, RunStatusOutput } from "../api/generated";
import { RunMonitor } from "./RunMonitor";

const runId = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function runStatus(
  state: RunStatusOutput["state"],
  lastSequence: number,
): RunStatusOutput {
  return { runId, state, lastSequence };
}

function runEvents(
  data: RunEventPageOutput["data"],
  nextAfterSequence: number,
  hasMore = false,
): RunEventPageOutput {
  return { data, nextAfterSequence, hasMore };
}

function runEvent(
  sequence: number,
  state: RunEventPageOutput["data"][number]["state"],
  message: string,
) {
  return {
    runId,
    sequence,
    state,
    message,
    occurredAt: "2026-11-15T12:00:00Z",
  };
}

function submitRunId() {
  fireEvent.change(screen.getByLabelText("Run ID"), {
    target: { value: runId },
  });
  fireEvent.submit(
    screen.getByRole("form", { name: "Open a persisted run" }),
  );
}

async function flushPendingWork() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("run monitor", () => {
  it("shows truthful empty guidance and does not fabricate a run", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<RunMonitor />);

    expect(
      screen.getByRole("heading", { name: "Run monitor", level: 1 }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/reads persisted run state only/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/enter a run ID/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads persisted status and event text, then polls from the last sequence", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(runStatus("RUNNING", 1)))
      .mockResolvedValueOnce(
        jsonResponse(
          runEvents([runEvent(1, "RUNNING", "<b>renderer ready</b>")], 1),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(runStatus("RUNNING", 2)))
      .mockResolvedValueOnce(
        jsonResponse(runEvents([runEvent(2, "RUNNING", "encode queued")], 2)),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<RunMonitor />);
    submitRunId();

    await flushPendingWork();
    expect(screen.getAllByText("Running")).toHaveLength(2);
    expect(screen.getByText("<b>renderer ready</b>")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    await flushPendingWork();

    expect(screen.getByText("encode queued")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock).toHaveBeenLastCalledWith(
      `/api/v1/runs/${runId}/events?afterSequence=1&limit=100`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(screen.getByText(/last complete refresh/i)).toBeInTheDocument();
  });

  it("replays multiple bounded pages and stops polling after a terminal state", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(runStatus("SUCCEEDED", 2)))
      .mockResolvedValueOnce(
        jsonResponse(
          runEvents([runEvent(1, "RUNNING", "started")], 1, true),
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          runEvents([runEvent(2, "SUCCEEDED", "finished")], 2, false),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<RunMonitor />);
    submitRunId();

    await flushPendingWork();
    expect(screen.getByText("finished")).toBeInTheDocument();
    expect(screen.getByText("Run finished")).toBeInTheDocument();
    const callCount = fetchMock.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(fetchMock).toHaveBeenCalledTimes(callCount);
  });

  it("retries from the last committed cursor if a later event page fails", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(runStatus("RUNNING", 2)))
      .mockResolvedValueOnce(
        jsonResponse(runEvents([runEvent(1, "RUNNING", "first event")], 1, true)),
      )
      .mockResolvedValueOnce(jsonResponse({ error: {} }, 503))
      .mockResolvedValueOnce(jsonResponse(runStatus("RUNNING", 2)))
      .mockResolvedValueOnce(
        jsonResponse(runEvents([runEvent(1, "RUNNING", "first event")], 1, true)),
      )
      .mockResolvedValueOnce(
        jsonResponse(runEvents([runEvent(2, "RUNNING", "second event")], 2)),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<RunMonitor />);
    submitRunId();
    await flushPendingWork();
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    await flushPendingWork();

    expect(fetchMock.mock.calls[4]?.[0]).toContain("afterSequence=0");
    expect(screen.getByText("first event")).toBeInTheDocument();
    expect(screen.getByText("second event")).toBeInTheDocument();
  });

  it("explains an owner authorization failure without showing a fake run", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ error: {} }, 403)),
    );

    render(<RunMonitor />);
    await user.type(screen.getByLabelText("Run ID"), runId);
    await user.click(screen.getByRole("button", { name: "Open run" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/owner access/i);
    expect(screen.queryByText("Running")).not.toBeInTheDocument();
  });

  it("clears saved run details when owner authorization is lost", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(runStatus("RUNNING", 1)))
        .mockResolvedValueOnce(
          jsonResponse(runEvents([runEvent(1, "RUNNING", "private event")], 1)),
        )
        .mockResolvedValueOnce(jsonResponse({ error: {} }, 403)),
    );

    render(<RunMonitor />);
    submitRunId();
    await flushPendingWork();
    expect(screen.getByText("private event")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    await flushPendingWork();

    expect(screen.getByRole("alert")).toHaveTextContent(/owner access/i);
    expect(screen.queryByText("private event")).not.toBeInTheDocument();
    expect(screen.queryByText(/through sequence/i)).not.toBeInTheDocument();
  });
});
