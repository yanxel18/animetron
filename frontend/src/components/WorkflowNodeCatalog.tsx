import { useEffect, useRef, useState } from "react";
import type { SampleNodeCatalogOutput } from "../api/generated";
import { fetchSampleNodeCatalog } from "../api/workflows";

export function WorkflowNodeCatalog({ onDenied, onCatalogChange }: {
  onDenied: (error: unknown) => boolean; onCatalogChange: (catalog: SampleNodeCatalogOutput | null) => void;
}) {
  const [catalog, setCatalog] = useState<SampleNodeCatalogOutput | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function load() {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError(null);
    setCatalog(null);
    onCatalogChange(null);
    try {
      const result = await fetchSampleNodeCatalog(request.signal);
      if (!request.signal.aborted) { setCatalog(result); onCatalogChange(result); }
    } catch (value) {
      if (!request.signal.aborted && !onDenied(value)) {
        setError(value instanceof Error ? value.message : "Could not load sample node types.");
      }
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }

  return <section className="sample-node-catalog" aria-labelledby="sample-node-catalog-title" aria-busy={loading}>
    <h2 id="sample-node-catalog-title">Sample node types</h2>
    <p>These definitions are used to validate sample workflows. This does not establish execution or model readiness.</p>
    <button type="button" className="button button--secondary" disabled={loading} onClick={() => void load()}>
      {catalog || error ? "Reload sample node types" : "Load sample node types"}
    </button>
    {loading && <p role="status">Loading sample node types…</p>}
    {error && <p role="alert">{error}</p>}
    {catalog && (catalog.nodes.length === 0 ? <p role="status">No sample node types are available.</p> :
      <ul aria-label="Sample validation node types">
        {catalog.nodes.map((node) => <li key={node.type}>
          <h3>{node.type}</h3>
          <p>Inputs: {node.inputs.length ? node.inputs.map((port) => `${port.name} (${port.type}${port.required ? ", required" : ""})`).join(", ") : "none"}</p>
          <p>Outputs: {node.outputs.length ? node.outputs.map((port) => `${port.name} (${port.type})`).join(", ") : "none"}</p>
          {node.configSchema === null ? <p>Configuration must be an empty object.</p> : <>
            <p>Configuration schema:</p>
            <pre className="workflow-json" tabIndex={0} aria-label={`Configuration schema for ${node.type}`}><code>{JSON.stringify(node.configSchema, null, 2)}</code></pre>
          </>}
        </li>)}
      </ul>)}
  </section>;
}
