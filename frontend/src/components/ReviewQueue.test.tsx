import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewMetadataResponse, ReviewPageResponse } from "../api/generated";
import { ReviewQueue } from "./ReviewQueue";

const firstReview: ReviewMetadataResponse = {
  id: "3e3f44c7-f1ae-4c62-9afd-8146ddb19179",
  runId: "3986b877-6311-4193-9a9e-30788e8c8787",
  artifactRevision: "revision-7",
  artifactSha256: "a".repeat(64),
  captionSha256: "b".repeat(64),
  destinations: [{ provider: "facebook", accountId: "page-42" }],
  expiresAt: "2026-11-16T12:00:00Z",
  createdAt: "2026-11-15T12:00:00Z",
  state: "AWAITING_DECISION",
  stateChangedAt: "2026-11-15T12:30:00Z",
  deliveryErrorCode: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("review queue", () => {
  it("shows owner-only review metadata without offering an unsafe decision", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ data: [firstReview], nextCursor: null } satisfies ReviewPageResponse),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ReviewQueue />);

    expect(await screen.findByText("Awaiting decision")).toBeInTheDocument();
    expect(screen.getByText("revision-7")).toBeInTheDocument();
    expect(screen.getByText("facebook · page-42")).toBeInTheDocument();
    expect(
      screen.getByText(/exact video and caption preview are not available/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /approve|reject/i }),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/reviews?limit=50",
      expect.objectContaining({
        cache: "no-store",
        credentials: "same-origin",
      }),
    );
  });

  it("renders all destinations returned by the backend contract", async () => {
    const destinations = Array.from({ length: 21 }, (_, index) => ({
      provider: `provider-${index}`,
      accountId: `account-${index}`,
    }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          data: [{ ...firstReview, destinations }],
          nextCursor: null,
        }),
      ),
    );

    render(<ReviewQueue />);

    expect(
      await screen.findByText("provider-20 · account-20"),
    ).toBeInTheDocument();
  });

  it("appends subsequent pages using the opaque cursor", async () => {
    const secondReview = {
      ...firstReview,
      id: "f22de8c1-3bd3-4308-87e0-e302cb38d1f6",
      runId: "b09824a7-6c8c-4959-984f-ec47700e9d39",
      artifactRevision: "revision-8",
      state: "APPROVED" as const,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ data: [firstReview], nextCursor: "opaque-cursor" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ data: [secondReview], nextCursor: null }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<ReviewQueue />);
    await screen.findByText("Awaiting decision");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Approved")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/v1/reviews?limit=50&cursor=opaque-cursor",
        expect.objectContaining({ credentials: "same-origin" }),
      );
    });
  });

  it("retries a failed next page without restarting the loaded page", async () => {
    const secondReview = {
      ...firstReview,
      id: "f22de8c1-3bd3-4308-87e0-e302cb38d1f6",
      runId: "b09824a7-6c8c-4959-984f-ec47700e9d39",
      artifactRevision: "revision-8",
      state: "APPROVED" as const,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ data: [firstReview], nextCursor: "opaque-cursor" }),
      )
      .mockRejectedValueOnce(new Error("temporary network error"))
      .mockResolvedValueOnce(
        jsonResponse({ data: [secondReview], nextCursor: null }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<ReviewQueue />);
    await screen.findByText("Awaiting decision");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Retry loading more" }),
    );

    expect(await screen.findByText("Approved")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/reviews?limit=50&cursor=opaque-cursor",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(screen.getByText("revision-7")).toBeInTheDocument();
    expect(screen.getByText("revision-8")).toBeInTheDocument();
  });

  it("explains authorization failures and allows retry", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ error: { code: "FORBIDDEN" } }, 403),
      )
      .mockResolvedValueOnce(jsonResponse({ data: [], nextCursor: null }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ReviewQueue />);

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(/owner access is required/i);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByText(/no review requests are available/i),
    ).toBeInTheDocument();
  });

  it("does not present a stale queue as current after refresh fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ data: [firstReview], nextCursor: null }),
        )
        .mockRejectedValueOnce(new Error("temporary network error")),
    );

    render(<ReviewQueue />);
    expect(await screen.findByText("revision-7")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh queue" }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("revision-7")).not.toBeInTheDocument();
  });

  it("rejects malformed queue responses instead of rendering partial data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ data: [{ ...firstReview, state: "UNKNOWN" }], nextCursor: null }),
      ),
    );

    render(<ReviewQueue />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /invalid response/i,
    );
    expect(screen.queryByText("revision-7")).not.toBeInTheDocument();
  });
});
