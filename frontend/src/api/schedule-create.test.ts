import { afterEach, describe, expect, it, vi } from "vitest";

import type { DescriptorInput, DescriptorOutput } from "./generated";
import { createScheduleDescriptor } from "./schedule-create";

const pendingKey = "animetron.schedule-create.pending.v1";
const input: DescriptorInput = {
  workflowId: "3986b877-6311-4193-9a9e-30788e8c8787",
  revision: "release/α<&>",
  expression: "0 9 * * *",
  timeZone: "Asia/Tokyo",
  enabled: false,
  overlapPolicy: "skip",
  missedRunPolicy: "skip",
};
const descriptor: DescriptorOutput = {
  id: "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53",
  ...input,
  nextDueAt: null,
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

function installLocks(
  request: (callback: (lock: Lock | null) => Promise<unknown>) => Promise<unknown> =
    async (callback) => callback({ name: "test-lock", mode: "exclusive" } as Lock),
) {
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: { request: vi.fn((_name: string, _options: unknown, callback: (lock: Lock | null) => Promise<unknown>) => request(callback)) },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.removeItem(pendingKey);
  Reflect.deleteProperty(navigator, "locks");
});

describe("createScheduleDescriptor", () => {
  it("accepts a FEFF-only revision unchanged in the request and verified response", async () => {
    const selection = { ...input, revision: "\uFEFF" };
    const saved = { ...descriptor, revision: selection.revision };
    installLocks();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response(saved, 201));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(selection)).resolves.toEqual(saved);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual(selection);
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it.each(["\u001c", "\u001d", "\u001e", "\u001f", "\u0085"])(
    "rejects Python whitespace-only revision %j before network access",
    async (revision) => {
      installLocks();
      const fetchMock = vi.fn()
        .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
        .mockResolvedValueOnce(response({ ...descriptor, revision }, 201));
      vi.stubGlobal("fetch", fetchMock);

      await expect(createScheduleDescriptor({ ...input, revision }))
        .rejects.toMatchObject({ status: 422, uncertain: false });
      expect(fetchMock).not.toHaveBeenCalled();
      expect(localStorage.getItem(pendingKey)).toBeNull();
    },
  );

  it("uses a fresh owner CSRF session and validates the exact 201 descriptor", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockImplementationOnce(async (url: string, options: RequestInit) => {
        expect(localStorage.getItem(pendingKey)).toBe("pending");
        expect(url).toBe("/api/v1/schedules");
        expect(options.method).toBe("POST");
        expect(options.credentials).toBe("same-origin");
        expect(options.cache).toBe("no-store");
        expect(options.headers).toMatchObject({
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": "test-csrf",
        });
        expect(JSON.parse(String(options.body))).toEqual(input);
        return response(descriptor, 201);
      });
    installLocks();
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(input)).resolves.toEqual(descriptor);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/session");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("refuses a second attempt from a persisted marker unless the user acknowledges uncertainty", async () => {
    localStorage.setItem(pendingKey, "pending");
    installLocks();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response(descriptor, 201));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({
      uncertain: true,
      requiresAcknowledgement: true,
    });
    expect(fetchMock).not.toHaveBeenCalled();

    await expect(createScheduleDescriptor(input, { acknowledgeUncertain: true }))
      .resolves.toEqual(descriptor);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not submit without owner access or a valid CSRF session", async () => {
    installLocks();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ role: "viewer", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "bad\nheader" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({ status: 403 });
    await expect(createScheduleDescriptor(input)).rejects.toThrow(/invalid response/i);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("keeps uncertainty durable after a 503 and never retries automatically", async () => {
    installLocks();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({}, 503));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({ uncertain: true, status: 503 });
    expect(localStorage.getItem(pendingKey)).toBe("pending");
    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({ requiresAcknowledgement: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["network failure", async () => { throw new TypeError("disconnected"); }],
    ["malformed successful response", async () => response({ id: "not-a-descriptor" }, 201)],
    ["unexpected successful status", async () => response(descriptor, 200)],
  ])("retains the marker after %s", async (_label, postResponse) => {
    installLocks();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockImplementationOnce(postResponse));

    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({ uncertain: true });
    expect(localStorage.getItem(pendingKey)).toBe("pending");
  });

  it.each([409, 422])("clears the marker after definitive HTTP %i rejection", async (status) => {
    installLocks();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({}, status)));

    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({
      status,
      uncertain: false,
    });
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("keeps an older uncertain marker after an acknowledged attempt is rejected", async () => {
    localStorage.setItem(pendingKey, "pending");
    installLocks();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({}, 409)));

    await expect(createScheduleDescriptor(input, { acknowledgeUncertain: true }))
      .rejects.toMatchObject({ status: 409, uncertain: false });
    expect(localStorage.getItem(pendingKey)).toBe("pending");
  });

  it("does not treat a later confirmed descriptor as proof that an older unknown attempt failed", async () => {
    localStorage.setItem(pendingKey, "pending");
    installLocks();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response(descriptor, 201)));

    await expect(createScheduleDescriptor(input, { acknowledgeUncertain: true }))
      .resolves.toEqual(descriptor);
    expect(localStorage.getItem(pendingKey)).toBe("pending");
  });

  it("fails closed if browser locking is unavailable", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(input)).rejects.toThrow(/safe creation is unavailable/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed when another browser tab holds the exclusive attempt lock", async () => {
    installLocks(async (callback) => callback(null));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(input)).rejects.toThrow(/another schedule creation is in progress/i);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("rejects descriptor fields outside the generated server contract before network access", async () => {
    installLocks();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor({ ...input, expression: "x".repeat(257) }))
      .rejects.toMatchObject({ status: 422, uncertain: false });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("does not leave an uncertainty marker when owner session discovery fails before POST", async () => {
    installLocks();
    const fetchMock = vi.fn().mockResolvedValue(response({}, 503));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({
      status: 503,
      uncertain: false,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(pendingKey)).toBeNull();
  });

  it("does not clear the marker when the 201 body does not match the submitted selection", async () => {
    installLocks();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response({ role: "owner", csrfToken: "test-csrf" }))
      .mockResolvedValueOnce(response({ ...descriptor, revision: "different-revision" }, 201)));

    await expect(createScheduleDescriptor(input)).rejects.toMatchObject({ uncertain: true });
    expect(localStorage.getItem(pendingKey)).toBe("pending");
  });
});
