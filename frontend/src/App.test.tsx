import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("creator studio foundation", () => {
  it("keeps unavailable screens and workflow actions disabled with visible reasons", () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "Studio" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "Runs" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Review" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Run workflow" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Run workflow" }),
    ).toHaveAccessibleDescription(/not implemented in P7-01/i);
  });

  it("shows truthful empty states instead of a fabricated workflow or run", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "No workflow is loaded" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Inspector" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "No run is loaded" }),
    ).toBeInTheDocument();
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
});
