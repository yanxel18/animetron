import { useEffect, useRef, useState } from "react";

import type { ArtifactMetadataOutput } from "../api/generated";
import {
  ArtifactMetadataError,
  artifactMetadataErrorMessage,
  fetchArtifactMetadata,
  isArtifactId,
} from "../api/artifacts";
import { ArtifactMetadataCard } from "./ArtifactMetadataCard";

export function ArtifactLibrary() {
  const [artifactIdInput, setArtifactIdInput] = useState("");
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [metadata, setMetadata] = useState<ArtifactMetadataOutput | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const errorSummary = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (artifactId === null) return;

    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError(null);
    setMetadata(null);

    void fetchArtifactMetadata(artifactId, request.signal)
      .then((result) => {
        if (!request.signal.aborted) setMetadata(result);
      })
      .catch((requestError: unknown) => {
        if (!request.signal.aborted) setError(requestError);
      })
      .finally(() => {
        if (!request.signal.aborted) setLoading(false);
      });

    return () => request.abort();
  }, [artifactId, attempt]);

  useEffect(() => {
    if (error !== null) errorSummary.current?.focus();
  }, [error]);

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextId = artifactIdInput.trim().toLowerCase();
    controller.current?.abort();
    setMetadata(null);
    setError(null);

    if (!isArtifactId(nextId)) {
      setArtifactId(null);
      setLoading(false);
      setError(new ArtifactMetadataError("Enter a valid artifact ID.", 422));
      return;
    }

    setLoading(true);
    setArtifactId(nextId);
    setAttempt((current) => current + 1);
  }

  function handleInputChange(value: string) {
    controller.current?.abort();
    setArtifactIdInput(value);
    setArtifactId(null);
    setMetadata(null);
    setError(null);
    setLoading(false);
  }

  const errorStatus =
    error instanceof ArtifactMetadataError ? error.status : null;

  return (
    <section
      id="library"
      className="artifact-library"
      aria-labelledby="artifact-library-title"
      aria-busy={loading}
      tabIndex={-1}
    >
      <header className="page-heading">
        <div className="page-title">
          <p className="eyebrow">STORED OUTPUTS</p>
          <h1 id="artifact-library-title" tabIndex={-1}>
            Library
          </h1>
          <p className="page-description">
            Look up metadata for an artifact ID you already have.
          </p>
        </div>
      </header>

      <p className="run-monitor-guidance" role="note">
        This owner-only lookup shows artifact metadata. It does not list
        artifacts or preview bytes.
      </p>

      <form
        className="artifact-lookup-form"
        aria-label="Look up artifact metadata"
        onSubmit={handleSubmit}
      >
        <div className="artifact-id-field">
          <label htmlFor="artifact-id">Artifact ID</label>
          <input
            id="artifact-id"
            autoComplete="off"
            required
            pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
            title="Enter a valid version-4 UUID artifact ID."
            value={artifactIdInput}
            onChange={(event) => handleInputChange(event.target.value)}
            aria-describedby="artifact-id-help"
          />
          <p id="artifact-id-help" className="run-field-help">
            Use the UUID from an existing artifact receipt.
          </p>
        </div>
        <button
          className="button button--primary"
          type="submit"
          disabled={loading}
        >
          {loading ? "Looking up..." : "Look up metadata"}
        </button>
      </form>

      {loading && (
        <p className="review-queue-status" role="status">
          Looking up artifact metadata...
        </p>
      )}

      {error !== null && (
        <div
          ref={errorSummary}
          className="review-error"
          role="alert"
          tabIndex={-1}
        >
          <p>{artifactMetadataErrorMessage(error)}</p>
          {errorStatus === 401 && (
            <a className="review-login-link" href="/api/v1/auth/login">
              Sign in
            </a>
          )}
        </div>
      )}

      {!loading && error === null && metadata === null && (
        <div className="run-monitor-empty">
          <p className="panel-kicker">NO ARTIFACT SELECTED</p>
          <h2>Enter an artifact ID to begin</h2>
          <p>
            Metadata appears after you provide an ID for an authorized,
            persisted artifact.
          </p>
        </div>
      )}

      {metadata !== null && <ArtifactMetadataCard metadata={metadata} />}
    </section>
  );
}
