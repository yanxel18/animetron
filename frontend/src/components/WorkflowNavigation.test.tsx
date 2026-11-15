import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { App } from "../App";

it("opens workflow discovery from studio navigation", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: [], nextCursor: null }))));
  render(<App />);
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  expect(await screen.findByRole("heading", { name: "Workflows" })).toBeInTheDocument();
  vi.unstubAllGlobals();
});
