import { afterEach, describe, expect, it, vi } from "vitest";

import type { ArtifactMetadataOutput } from "./generated";
import {
  artifactMetadataErrorMessage,
  fetchArtifactMetadata,
} from "./artifacts";

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

describe("artifact metadata API", () => {
  it("reads only metadata with a same-origin, uncached GET", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(metadata));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchArtifactMetadata(artifactId)).resolves.toEqual(metadata);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/artifacts/${artifactId}`,
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      }),
    );
  });

  it("rejects malformed artifact IDs before making a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    let message: string | undefined;
    try {
      await fetchArtifactMetadata("../runs");
    } catch (error: unknown) {
      message = artifactMetadataErrorMessage(error);
    }

    expect(message).toMatch(/valid artifact ID/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects responses that do not match the requested artifact", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ ...metadata, id: "2f7bc3a0-1222-4e88-82c1-a903f4a91dcb" }),
      ),
    );

    await expect(fetchArtifactMetadata(artifactId)).rejects.toThrow(
      /invalid response/i,
    );
  });

  it("rejects extra response fields such as storage locators or bytes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ ...metadata, storageLocator: "artifacts/private-path" }),
      ),
    );

    await expect(fetchArtifactMetadata(artifactId)).rejects.toThrow(
      /invalid response/i,
    );
  });

  it("provides safe, distinct messages for access and availability errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({}, 401))
        .mockResolvedValueOnce(jsonResponse({}, 403))
        .mockResolvedValueOnce(jsonResponse({}, 404))
        .mockResolvedValueOnce(jsonResponse({}, 503)),
    );

    const messages = await Promise.all(
      Array.from({ length: 4 }, async () => {
        try {
          await fetchArtifactMetadata(artifactId);
        } catch (error: unknown) {
          return artifactMetadataErrorMessage(error);
        }
        return "unexpected success";
      }),
    );

    expect(messages).toEqual([
      "Sign in to view artifact metadata.",
      "Owner access is required to view artifact metadata.",
      "The artifact was not found or is unavailable.",
      "Artifact metadata is unavailable. Try again.",
    ]);
  });
});
