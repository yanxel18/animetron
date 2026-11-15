import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScheduleList } from "./ScheduleList";

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

describe("saved schedules", () => {
  it("renders a saved descriptor without implying scheduler dispatch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      response({ data: [schedule], nextCursor: null }),
    ));
    render(<ScheduleList />);

    expect(await screen.findByText("0 9 * * *")).toBeInTheDocument();
    expect(screen.getByText("Asia/Tokyo")).toBeInTheDocument();
    expect(screen.getByText(/dispatch is not implemented/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create|edit|pause|resume/i }))
      .not.toBeInTheDocument();
  });

  it("shows a real empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ data: [], nextCursor: null })));
    render(<ScheduleList />);
    expect(await screen.findByText(/no saved schedules/i)).toBeInTheDocument();
  });

  it("retries a failed next page without discarding the current page", async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 50 }, (_, index) => ({
      ...schedule,
      id: `c4f7bcac-39e8-47a5-a9e1-${String(index).padStart(12, "0")}`,
    }));
    const cursor = items[49]!.id;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ data: items, nextCursor: cursor }))
      .mockResolvedValueOnce(response({}, 503))
      .mockResolvedValueOnce(response({ data: [], nextCursor: null }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ScheduleList />);

    await screen.findByText(items[0]!.id);
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unavailable/i);
    expect(screen.getByText(items[0]!.id)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText(items[0]!.id)).toBeInTheDocument();
    expect(fetchMock.mock.calls[2]?.[0]).toContain(`cursor=${cursor}`);
  });

  it("clears previously loaded data after owner access is revoked", async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 50 }, (_, index) => ({
      ...schedule,
      id: `c4f7bcac-39e8-47a5-a9e1-${String(index).padStart(12, "0")}`,
    }));
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response({ data: items, nextCursor: items[49]!.id }))
      .mockResolvedValueOnce(response({}, 403)));
    render(<ScheduleList />);
    await screen.findByText(items[0]!.id);
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/owner access/i);
    expect(screen.queryByText(items[0]!.id)).not.toBeInTheDocument();
  });
});
