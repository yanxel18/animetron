import { afterEach, describe, expect, it, vi } from "vitest";

import type { DescriptorOutput } from "./generated";
import { fetchSchedulePage, fetchSchedulePreview, scheduleErrorMessage, setScheduleEnabled } from "./schedules";

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
} satisfies DescriptorOutput;

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("schedule preview API", () => {
    const occurrences = Array.from({ length: 5 }, (_, index) => ({
      localTime: `2026-11-${16 + index}T09:00:00+09:00`,
      dueAt: `2026-11-${16 + index}T00:00:00Z`,
      slotKey: `Asia/Tokyo:2026-11-${16 + index}T09:00`,
    }));

    it("uses a fresh owner session token for a read-only preview", async () => {
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
        .mockResolvedValueOnce(response({ occurrences }));
      vi.stubGlobal("fetch", fetchMock);
      await expect(fetchSchedulePreview(id)).resolves.toEqual({ occurrences });
      expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/session");
      expect(fetchMock.mock.calls[1]).toEqual([
        `/api/v1/schedules/${id}/previews`,
        expect.objectContaining({
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: expect.objectContaining({ "X-CSRF-Token": "test-csrf" }),
          body: "{}",
        }),
      ]);
    });

    it("does not submit a preview when the session is not an owner", async () => {
      const fetchMock = vi.fn().mockResolvedValue(response({ role: "viewer", csrfToken: "test-csrf" }));
      vi.stubGlobal("fetch", fetchMock);
      await expect(fetchSchedulePreview(id)).rejects.toMatchObject({ status: 403 });
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("does not submit a preview for a malformed session", async () => {
      const fetchMock = vi.fn().mockResolvedValue(response({ role: "owner", csrfToken: "bad\nheader" }));
      vi.stubGlobal("fetch", fetchMock);
      await expect(fetchSchedulePreview(id)).rejects.toThrow(/invalid response/i);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("rejects malformed or incomplete preview responses", async () => {
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
        .mockResolvedValueOnce(response({ occurrences: occurrences.slice(0, 4) }))
        .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
        .mockResolvedValueOnce(response({ occurrences: [{ ...occurrences[0], dueAt: "bad" }, ...occurrences.slice(1)] }));
      vi.stubGlobal("fetch", fetchMock);
      await expect(fetchSchedulePreview(id)).rejects.toThrow(/invalid response/i);
      await expect(fetchSchedulePreview(id)).rejects.toThrow(/invalid response/i);
    });

    it("rejects non-UTC due times rather than labeling them UTC", async () => {
      vi.stubGlobal("fetch", vi.fn()
        .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
        .mockResolvedValueOnce(response({
          occurrences: occurrences.map((occurrence) => ({ ...occurrence, dueAt: occurrence.localTime })),
        })));
      await expect(fetchSchedulePreview(id)).rejects.toThrow(/invalid response/i);
    });
});

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

describe("schedule pause and resume", () => {
  it("uses the displayed version and preserves all other settings", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({ ...schedule, enabled: false, nextDueAt: null, version: 2 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(setScheduleEnabled(schedule, false)).resolves.toMatchObject({ enabled: false, version: 2 });
    expect(fetchMock.mock.calls[1]).toEqual([
      `/api/v1/schedules/${id}`,
      expect.objectContaining({
        method: "PUT",
        headers: expect.objectContaining({ "X-CSRF-Token": "test-csrf" }),
        body: JSON.stringify({
          workflowId: schedule.workflowId, revision: schedule.revision,
          expression: schedule.expression, timeZone: schedule.timeZone, enabled: false,
          overlapPolicy: "skip", missedRunPolicy: "skip", expectedVersion: 1,
        }),
      }),
    ]);
  });

  it("does not mutate when the session is not an owner", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ role: "viewer", csrfToken: "test-csrf" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(setScheduleEnabled(schedule, false)).rejects.toMatchObject({ status: 403 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a conflicting or malformed update without retrying", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({}, 409))
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({ ...schedule, enabled: false, version: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(setScheduleEnabled(schedule, false)).rejects.toMatchObject({ status: 409 });
    await expect(setScheduleEnabled(schedule, false)).rejects.toThrow(/invalid response/i);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});
