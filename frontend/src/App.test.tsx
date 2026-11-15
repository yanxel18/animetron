import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("creator studio foundation", () => {
  it("keeps unavailable screens and workflow actions disabled with visible reasons", () => {
    render(<App />);

    expect(screen.getByRole("link", { name: "Studio" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "Runs" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Review" })).toBeDisabled();
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
});
