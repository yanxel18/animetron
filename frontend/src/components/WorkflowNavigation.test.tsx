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

it("preserves an unsaved draft when switching studio sections", async () => {
  const id = "12345678-1234-4234-8234-123456789abc";
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    return new Response(JSON.stringify(path.includes("/draft")
      ? { workflowId: id, version: 1, document: "{}" }
      : { data: [], nextCursor: null }));
  }));
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole("link", { name: "Workflows" }));
  await user.type(screen.getByLabelText("Workflow ID"), id);
  await user.click(screen.getByRole("button", { name: "Load draft" }));
  const editor = await screen.findByLabelText("Workflow draft JSON");
  await user.type(editor, "x");
  await user.click(screen.getByRole("link", { name: /^Studio$/ }));
  await user.click(screen.getByRole("link", { name: "Workflows" }));
  expect(screen.getByLabelText("Workflow draft JSON")).toHaveValue("{}x");
  vi.unstubAllGlobals();
});
