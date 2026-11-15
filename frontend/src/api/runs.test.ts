import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunEventPageOutput, RunStatusOutput } from "./generated";
import {
  fetchRunEvents,
  fetchRunStatus,
  runMonitorErrorMessage,
} from "./runs";

const runId = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("run monitor API", () => {
  it("reads persisted status without caching and rejects unsafe run IDs", async () => {
    const status: RunStatusOutput = {
      runId,
      state: "RUNNING",
      lastSequence: 4,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(status));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchRunStatus(runId)).resolves.toEqual(status);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/runs/${runId}`,
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
    await expect(fetchRunStatus("../reviews")).rejects.toThrow(
      /valid run ID/i,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("replays bounded ordered events from the exclusive cursor", async () => {
    const page: RunEventPageOutput = {
      data: [
        {
          runId,
          sequence: 3,
          state: "RUNNING",
          message: "<script>not html</script>",
          occurredAt: "2026-11-15T12:00:00Z",
        },
      ],
      nextAfterSequence: 3,
      hasMore: false,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(page));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchRunEvents(runId, 2)).resolves.toEqual(page);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/runs/${runId}/events?afterSequence=2&limit=100`,
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("rejects malformed or out-of-order event pages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          data: [
            {
              runId,
              sequence: 5,
              state: "RUNNING",
              message: "first",
              occurredAt: "2026-11-15T12:00:00Z",
            },
            {
              runId,
              sequence: 4,
              state: "RUNNING",
              message: "out of order",
              occurredAt: "2026-11-15T12:01:00Z",
            },
          ],
          nextAfterSequence: 4,
          hasMore: false,
        }),
      ),
    );

    await expect(fetchRunEvents(runId, 2)).rejects.toThrow(/invalid response/i);
  });

  it("provides distinct guidance for authorization and missing-run errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ error: {} }, 401))
        .mockResolvedValueOnce(jsonResponse({ error: {} }, 403))
        .mockResolvedValueOnce(jsonResponse({ error: {} }, 404)),
    );

    const unauthorized = await fetchRunStatus(runId).catch((error: unknown) =>
      runMonitorErrorMessage(error),
    );
    const forbidden = await fetchRunStatus(runId).catch((error: unknown) =>
      runMonitorErrorMessage(error),
    );
    const missing = await fetchRunStatus(runId).catch((error: unknown) =>
      runMonitorErrorMessage(error),
    );

    expect(unauthorized).toMatch(/sign in/i);
    expect(forbidden).toMatch(/owner access/i);
    expect(missing).toMatch(/run was not found/i);
  });
});
