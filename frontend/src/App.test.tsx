import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("creator studio foundation", () => {
  it("keeps unavailable sections and workflow actions disabled with visible reasons", () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "Studio" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Runs" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "Library" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Models" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Review" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Run workflow" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Run workflow" }),
    ).toHaveAccessibleDescription(/not implemented in P7-01/i);
  });

  it("opens the metadata-only Library from navigation without querying until requested", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await user.click(screen.getByRole("link", { name: "Library" }));

    expect(
      screen.getByRole("heading", { name: "Library", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("main", { name: "Library workspace" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Skip to workspace" })).toHaveAttribute(
      "href",
      "#artifact-library-title",
    );
    expect(fetchMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("link", { name: "Skip to workspace" }));
    expect(window.location.hash).toBe("#artifact-library-title");
  });

  it("shows a truthful workflow empty state and links to persisted run history", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "No workflow is loaded" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Inspector" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Runs" })).toBeInTheDocument();
  });

  it("lets keyboard users skip navigation and toggle the mobile menu", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to workspace" })).toHaveFocus();

    const openButton = screen.getByRole("button", { name: "Open navigation" });
    await user.tab();
    expect(openButton).toHaveFocus();
    expect(openButton).toHaveAttribute("aria-expanded", "false");
    await user.keyboard("{Enter}");
    expect(
      screen.getByRole("button", { name: "Close navigation" }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  it("opens the owner review queue from workspace navigation", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ data: [], nextCursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(<App />);

    await user.click(screen.getByRole("link", { name: "Review" }));

    expect(
      await screen.findByRole("heading", {
        name: "Review queue",
        level: 1,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByText(/no review requests are available/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Studio", level: 1 }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Skip to workspace" }));
    expect(window.location.hash).toBe("#review-queue-title");
    expect(
      screen.getByRole("heading", { name: "Review queue", level: 1 }),
    ).toBeInTheDocument();
  });

  it("opens the persisted run monitor from workspace navigation", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("link", { name: "Runs" }));

    expect(
      screen.getByRole("heading", { name: "Run monitor", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Run ID")).toBeVisible();
    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Skip to workspace" })).toHaveAttribute(
      "href",
      "#run-monitor-title",
    );
    expect(
      screen.queryByRole("heading", { name: "Studio", level: 1 }),
    ).not.toBeInTheDocument();
  });

  it("opens saved schedules with an accessible skip target", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ data: [], nextCursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(<App />);

    await user.click(screen.getByRole("link", { name: "Schedules" }));
    expect(await screen.findByText(/no saved schedules/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Schedules" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Skip to workspace" }))
      .toHaveAttribute("href", "#schedule-list-title");
    expect(screen.queryByRole("heading", { name: "Studio", level: 1 }))
      .not.toBeInTheDocument();
  });

  it("closes the mobile menu on Escape and returns focus to its toggle", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.tab();
    await user.tab();
    await user.keyboard("{Enter}");
    await user.tab();
    expect(screen.getByRole("link", { name: "Studio" })).toHaveFocus();

    await user.keyboard("{Escape}");

    const openButton = screen.getByRole("button", { name: "Open navigation" });
    expect(openButton).toHaveAttribute("aria-expanded", "false");
    expect(openButton).toHaveFocus();
  });

  it("keeps the review queue open when closing mobile navigation with Escape", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ data: [], nextCursor: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    render(<App />);

    await user.click(screen.getByRole("link", { name: "Review" }));
    await screen.findByRole("heading", { name: "Review queue" });
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.tab();
    await user.keyboard("{Escape}");

    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveFocus();
    expect(screen.getByRole("heading", { name: "Review queue" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
