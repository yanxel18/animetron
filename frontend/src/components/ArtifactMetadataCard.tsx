import type { ArtifactMetadataOutput } from "../api/generated";

interface ArtifactMetadataCardProps {
  metadata: ArtifactMetadataOutput;
}

export function ArtifactMetadataCard({
  metadata,
}: ArtifactMetadataCardProps) {
  return (
    <section
      className="panel artifact-metadata"
      aria-labelledby="artifact-metadata-title"
    >
      <header className="panel-heading">
        <div>
          <p className="panel-kicker">METADATA ONLY</p>
          <h2 id="artifact-metadata-title">Artifact metadata</h2>
        </div>
      </header>
      <p className="review-queue-status" role="status">
        Metadata loaded for this artifact.
      </p>
      <dl className="review-metadata">
        <div>
          <dt>Artifact ID</dt>
          <dd>
            <code>{metadata.id}</code>
          </dd>
        </div>
        <div>
          <dt>Owner ID</dt>
          <dd>
            <code>{metadata.ownerId}</code>
          </dd>
        </div>
        <div>
          <dt>Revision</dt>
          <dd>
            <code>{metadata.revision}</code>
          </dd>
        </div>
        <div>
          <dt>SHA-256</dt>
          <dd>
            <code>{metadata.sha256}</code>
          </dd>
        </div>
        <div>
          <dt>Byte size</dt>
          <dd>{metadata.byteSize} bytes</dd>
        </div>
        <div>
          <dt>Media type</dt>
          <dd>{metadata.mediaType}</dd>
        </div>
      </dl>
    </section>
  );
}
