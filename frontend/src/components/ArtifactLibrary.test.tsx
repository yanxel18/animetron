import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ArtifactMetadataOutput } from "../api/generated";
import { ArtifactLibrary } from "./ArtifactLibrary";

const artifactId = "c4f7bcac-39e8-47a5-a9e1-ecb6b1db8a53";
const metadata: ArtifactMetadataOutput = {
  id: artifactId,
  ownerId: "owner-1",
  revision: "revision-7",
  sha256: "a".repeat(64),
  byteSize: 1_024,
  mediaType: "image/png",
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

describe("artifact library", () => {
  it("looks up metadata only after an artifact ID is submitted", async () => {
    const user = userEvent.setup();
    let resolveResponse!: (response: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<ArtifactLibrary />);

    expect(
      screen.getByText(/does not list artifacts or preview bytes/i),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Artifact ID"), artifactId);
    await user.click(screen.getByRole("button", { name: "Look up metadata" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      /looking up artifact metadata/i,
    );
    expect(
      screen.getByRole("button", { name: "Looking up..." }),
    ).toBeDisabled();
    resolveResponse(jsonResponse(metadata));

    expect(
      await screen.findByRole("heading", { name: "Artifact metadata" }),
    ).toBeInTheDocument();
    expect(screen.getByText("owner-1")).toBeInTheDocument();
    expect(screen.getByText("revision-7")).toBeInTheDocument();
    expect(screen.getByText("image/png")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Look up metadata" }),
    ).toBeEnabled();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/artifacts/${artifactId}`,
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });

  it("reports missing artifacts without presenting metadata", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({}, 404)),
    );
    render(<ArtifactLibrary />);

    await user.type(screen.getByLabelText("Artifact ID"), artifactId);
    await user.click(screen.getByRole("button", { name: "Look up metadata" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /artifact was not found or is unavailable/i,
    );
    expect(
      screen.queryByRole("heading", { name: "Artifact metadata" }),
    ).not.toBeInTheDocument();
  });

  it("clears previously loaded metadata when owner access is denied", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(metadata))
      .mockResolvedValueOnce(jsonResponse({}, 403));
    vi.stubGlobal("fetch", fetchMock);
    render(<ArtifactLibrary />);

    const input = screen.getByLabelText("Artifact ID");
    const lookupButton = screen.getByRole("button", {
      name: "Look up metadata",
    });
    await user.type(input, artifactId);
    await user.click(lookupButton);
    await screen.findByRole("heading", { name: "Artifact metadata" });

    await user.click(lookupButton);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /owner access is required/i,
    );
    expect(
      screen.queryByRole("heading", { name: "Artifact metadata" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("owner-1")).not.toBeInTheDocument();
  });
});
