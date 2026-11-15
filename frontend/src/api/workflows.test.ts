import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWorkflowPage, fetchRevisionPage } from "./workflows";

const id = "12345678-1234-4234-8234-123456789abc";
afterEach(() => vi.unstubAllGlobals());

describe("workflow discovery API", () => {
  it("requests a bounded workflow page with same-origin credentials", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: [{ workflowId: id }], nextCursor: null,
    })));
    vi.stubGlobal("fetch", fetcher);
    expect(await fetchWorkflowPage(null)).toEqual({ data: [{ workflowId: id }], nextCursor: null });
    expect(fetcher).toHaveBeenCalledWith("/api/v1/workflows?limit=50", expect.objectContaining({
      method: "GET", credentials: "same-origin", cache: "no-store",
    }));
  });

  it("rejects malformed or mismatched revision metadata", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: [{ workflowId: "wrong", revision: "v1", createdAt: "invalid" }], nextCursor: null,
    }))));
    await expect(fetchRevisionPage(id, null)).rejects.toThrow("invalid response");
  });

  it("accepts revision metadata containing 128 supplementary Unicode codepoints", async () => {
    const revision = "\u{1f600}".repeat(128);
    const page = { data: [{ workflowId: id, revision, createdAt: "2025-01-02T00:00:00Z" }], nextCursor: null };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(page))));
    await expect(fetchRevisionPage(id, null)).resolves.toEqual(page);
  });

  it("rejects revision metadata containing more than 128 Unicode codepoints", async () => {
    const revision = "\u{1f600}".repeat(129);
    const page = { data: [{ workflowId: id, revision, createdAt: "2025-01-02T00:00:00Z" }], nextCursor: null };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(page))));
    await expect(fetchRevisionPage(id, null)).rejects.toThrow("invalid response");
  });

  it("rejects a repeated cursor and preserves authorization status", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: [], nextCursor: "again" })))
      .mockResolvedValueOnce(new Response("", { status: 403 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(fetchWorkflowPage("again")).rejects.toThrow("invalid response");
    await expect(fetchRevisionPage(id, null)).rejects.toMatchObject({ status: 403 });
  });

  it("uses the supplied opaque revision cursor and rejects invalid response shapes", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: [], nextCursor: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: "not an array", nextCursor: null })));
    vi.stubGlobal("fetch", fetcher);
    await fetchRevisionPage(id, "opaque_cursor");
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/workflows/${id}/revisions?limit=50&cursor=opaque_cursor`,
      expect.objectContaining({ method: "GET" }),
    );
    await expect(fetchWorkflowPage(null)).rejects.toThrow("invalid response");
  });
});
