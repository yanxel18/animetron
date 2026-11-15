import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchSchedulePage, scheduleErrorMessage } from "./schedules";

const id = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
const schedule = {
  id,
  workflowId: "3986b877-6311-4193-9a9e-30788e8c8787",
  revision: "revision-1",
  expression: "0 9 * * *",
  timeZone: "Asia/Tokyo",
  enabled: true,
  nextDueAt: "2026-11-16T00:00:00Z",
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

afterEach(() => vi.unstubAllGlobals());

describe("schedule list API", () => {
  it("requests saved descriptors without caching or mutation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response({ data: [schedule], nextCursor: null }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchSchedulePage(null)).resolves.toEqual({
      data: [schedule],
      nextCursor: null,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/schedules?limit=50",
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("rejects malformed descriptor and cursor data", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          response({ data: [{ ...schedule, nextDueAt: "invalid" }], nextCursor: null }),
        )
        .mockResolvedValueOnce(response({ data: [], nextCursor: "invalid" })),
    );

    await expect(fetchSchedulePage(null)).rejects.toThrow(/invalid response/i);
    await expect(fetchSchedulePage(null)).rejects.toThrow(/invalid response/i);
  });

  it("reports owner authorization failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({}, 403)));
    const message = await fetchSchedulePage(null).catch((error: unknown) =>
      scheduleErrorMessage(error),
    );
    expect(message).toMatch(/owner access/i);
  });
});
