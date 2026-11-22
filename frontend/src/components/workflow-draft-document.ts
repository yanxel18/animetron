export type WorkflowNodeOrderItem = {
  id: string;
  type: string;
};

type ParsedWorkflowDraft = {
  order: WorkflowNodeOrderItem[];
  nodeRanges: { start: number; end: number }[];
  nodeArrayEnd: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function findArrayRanges(json: string, target: "nodes" | "edges"): { ranges: { start: number; end: number }[]; end: number } | null {
  let index = 0;
  let nodeRanges: { ranges: { start: number; end: number }[]; end: number } | null = null;
  const whitespace = /\s/;
  const skipWhitespace = () => {
    while (whitespace.test(json[index] ?? "")) index += 1;
  };
  const stringEnd = (start: number) => {
    for (let cursor = start + 1; cursor < json.length; cursor += 1) {
      if (json[cursor] === "\\") cursor += 1;
      else if (json[cursor] === "\"") return cursor + 1;
    }
    return -1;
  };

  function readValue(depth = 0, captureNodes = false): boolean {
    skipWhitespace();
    if (json[index] === "\"") {
      const end = stringEnd(index);
      if (end < 0) return false;
      index = end;
      return true;
    }
    if (json[index] === "{") {
      index += 1;
      const keys = new Set<string>();
      skipWhitespace();
      if (json[index] === "}") {
        index += 1;
        return true;
      }
      while (index < json.length) {
        skipWhitespace();
        if (json[index] !== "\"") return false;
        const keyStart = index;
        const keyEnd = stringEnd(keyStart);
        if (keyEnd < 0) return false;
        const key: unknown = JSON.parse(json.slice(keyStart, keyEnd));
        if (typeof key !== "string" || keys.has(key)) return false;
        keys.add(key);
        index = keyEnd;
        skipWhitespace();
        if (json[index] !== ":") return false;
        index += 1;
        if (!readValue(depth + 1, depth === 0 && key === target)) return false;
        skipWhitespace();
        if (json[index] === "}") {
          index += 1;
          return true;
        }
        if (json[index] !== ",") return false;
        index += 1;
      }
      return false;
    }
    if (json[index] === "[") {
      index += 1;
      const ranges: { start: number; end: number }[] = [];
      skipWhitespace();
      if (json[index] === "]") {
        if (captureNodes) nodeRanges = { ranges, end: index };
        index += 1;
        return true;
      }
      while (index < json.length) {
        skipWhitespace();
        const start = index;
        if (!readValue(depth + 1)) return false;
        if (captureNodes) ranges.push({ start, end: index });
        skipWhitespace();
        if (json[index] === "]") {
          if (captureNodes) nodeRanges = { ranges, end: index };
          index += 1;
          return true;
        }
        if (json[index] !== ",") return false;
        index += 1;
      }
      return false;
    }

    const start = index;
    while (index < json.length && !/[\s,\]}]/.test(json[index])) index += 1;
    return index > start;
  }

  try {
    // JSON.parse hides duplicate keys, making the visible node order ambiguous.
    if (!readValue()) return null;
    skipWhitespace();
    return index === json.length ? nodeRanges : null;
  } catch {
    return null;
  }
}

function parseWorkflowDraft(document: string): ParsedWorkflowDraft | null {
  let value: unknown;
  try {
    value = JSON.parse(document);
  } catch {
    return null;
  }
  const nodeRanges = findArrayRanges(document, "nodes");
  if (nodeRanges === null || !isRecord(value) || value.schemaVersion !== 1 ||
    typeof value.revision !== "string" || !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges)) {
    return null;
  }

  const order: WorkflowNodeOrderItem[] = [];
  const ids = new Set<string>();
  for (const candidate of value.nodes) {
    if (!isRecord(candidate) || typeof candidate.id !== "string" ||
      candidate.id.length === 0 || typeof candidate.type !== "string" ||
      !isRecord(candidate.config) || ids.has(candidate.id)) {
      return null;
    }
    ids.add(candidate.id);
    order.push({ id: candidate.id, type: candidate.type });
  }
  if (nodeRanges.ranges.length !== order.length) return null;
  return { nodeRanges: nodeRanges.ranges, nodeArrayEnd: nodeRanges.end, order };
}

export function appendWorkflowNode(document: string, node: string): string | null {
  if (new TextEncoder().encode(node).length > 32_768) return null;
  try { JSON.parse(node); } catch { return null; }
  const parsed = parseWorkflowDraft(document);
  const candidate = parseWorkflowDraft(`{"schemaVersion":1,"revision":"draft","nodes":[${node}],"edges":[]}`);
  if (!parsed || !candidate || candidate.order.length !== 1 ||
      parsed.order.some((item) => item.id === candidate.order[0].id)) return null;
  const insertion = `${parsed.order.length ? "," : ""}${node}`;
  const updated = document.slice(0, parsed.nodeArrayEnd) + insertion + document.slice(parsed.nodeArrayEnd);
  if (new TextEncoder().encode(updated).length > 32_768) return null;
  return updated;
}

export function appendWorkflowEdge(document: string, edge: string): string | null {
  if (new TextEncoder().encode(edge).length > 32_768 || !parseWorkflowDraft(document)) return null;
  const ranges = findArrayRanges(document, "edges");
  const wrapper = `{"schemaVersion":1,"revision":"draft","nodes":[],"edges":[${edge}]}`;
  const candidateRanges = findArrayRanges(wrapper, "edges");
  if (!ranges || !candidateRanges || candidateRanges.ranges.length !== 1) return null;
  try {
    JSON.parse(edge);
    const current: unknown = JSON.parse(document);
    const candidate: unknown = JSON.parse(wrapper);
    if (!isRecord(current) || !Array.isArray(current.edges) || !isRecord(candidate) ||
        !Array.isArray(candidate.edges) || candidate.edges.length !== 1) return null;
    const item: unknown = candidate.edges[0];
    if (!isRecord(item) || !["id", "source", "sourcePort", "target", "targetPort"].every(
      (key) => typeof item[key] === "string" && (item[key] as string).length > 0,
    )) return null;
    const ids = new Set<unknown>([item.id]);
    for (const existing of current.edges) {
      if (!isRecord(existing) || typeof existing.id !== "string" || !existing.id || ids.has(existing.id)) return null;
      ids.add(existing.id);
    }
    const updated = document.slice(0, ranges.end) + (current.edges.length ? "," : "") + edge + document.slice(ranges.end);
    return new TextEncoder().encode(updated).length <= 32_768 ? updated : null;
  } catch {
    return null;
  }
}

export function readWorkflowNodeOrder(document: string): WorkflowNodeOrderItem[] | null {
  return parseWorkflowDraft(document)?.order ?? null;
}

export function readWorkflowNodeSource(document: string, nodeId: string): string | null {
  const parsed = parseWorkflowDraft(document);
  if (!parsed) return null;
  const index = parsed.order.findIndex((node) => node.id === nodeId);
  if (index < 0) return null;
  const range = parsed.nodeRanges[index];
  return document.slice(range.start, range.end);
}

export function replaceWorkflowNode(document: string, nodeId: string, node: string): string | null {
  if (new TextEncoder().encode(node).length > 32_768) return null;
  try { JSON.parse(node); } catch { return null; }
  const parsed = parseWorkflowDraft(document);
  const candidate = parseWorkflowDraft(`{"schemaVersion":1,"revision":"draft","nodes":[${node}],"edges":[]}`);
  if (!parsed || !candidate || candidate.order.length !== 1 || candidate.order[0].id !== nodeId) return null;
  const index = parsed.order.findIndex((item) => item.id === nodeId);
  if (index < 0) return null;
  const range = parsed.nodeRanges[index];
  const updated = document.slice(0, range.start) + node + document.slice(range.end);
  return new TextEncoder().encode(updated).length <= 32_768 ? updated : null;
}

type WorkflowEdgeItem = { id: string; source: string; sourcePort: string; target: string; targetPort: string };

export function readWorkflowEdges(document: string): WorkflowEdgeItem[] | null {
  if (!parseWorkflowDraft(document) || !findArrayRanges(document, "edges")) return null;
  try {
    const value: unknown = JSON.parse(document);
    if (!isRecord(value) || !Array.isArray(value.edges)) return null;
    const result: WorkflowEdgeItem[] = [];
    const ids = new Set<string>();
    for (const edge of value.edges) {
      if (!isRecord(edge) || typeof edge.id !== "string" || !edge.id || ids.has(edge.id) ||
          typeof edge.source !== "string" || !edge.source || typeof edge.sourcePort !== "string" || !edge.sourcePort ||
          typeof edge.target !== "string" || !edge.target || typeof edge.targetPort !== "string" || !edge.targetPort) return null;
      ids.add(edge.id);
      result.push({ id: edge.id, source: edge.source, sourcePort: edge.sourcePort, target: edge.target, targetPort: edge.targetPort });
    }
    return result;
  } catch { return null; }
}

export function removeWorkflowEdge(document: string, edgeId: string): string | null {
  const edges = readWorkflowEdges(document);
  const ranges = findArrayRanges(document, "edges")?.ranges;
  if (!edges || !ranges || ranges.length !== edges.length) return null;
  const index = edges.findIndex((edge) => edge.id === edgeId);
  if (index < 0) return null;
  const start = index === ranges.length - 1 && index > 0 ? ranges[index - 1].end : ranges[index].start;
  const end = index < ranges.length - 1 ? ranges[index + 1].start : ranges[index].end;
  return document.slice(0, start) + document.slice(end);
}

export function removeWorkflowNode(document: string, nodeId: string): string | null {
  const parsed = parseWorkflowDraft(document);
  if (!parsed) return null;
  const index = parsed.order.findIndex((node) => node.id === nodeId);
  if (index < 0) return null;
  try {
    const value: unknown = JSON.parse(document);
    if (!isRecord(value) || !Array.isArray(value.edges) || value.edges.some((edge: unknown) =>
      !isRecord(edge) || typeof edge.source !== "string" || typeof edge.target !== "string" ||
      edge.source === nodeId || edge.target === nodeId)) return null;
  } catch { return null; }
  const ranges = parsed.nodeRanges;
  const start = index === ranges.length - 1 && index > 0 ? ranges[index - 1].end : ranges[index].start;
  const end = index < ranges.length - 1 ? ranges[index + 1].start : ranges[index].end;
  return document.slice(0, start) + document.slice(end);
}

export function moveWorkflowNode(
  document: string,
  nodeId: string,
  direction: "up" | "down",
): string | null {
  const parsed = parseWorkflowDraft(document);
  if (!parsed) return null;

  const index = parsed.order.findIndex((node) => node.id === nodeId);
  const nextIndex = index + (direction === "up" ? -1 : 1);
  if (index < 0 || nextIndex < 0 || nextIndex >= parsed.order.length) return null;

  const first = parsed.nodeRanges[Math.min(index, nextIndex)];
  const second = parsed.nodeRanges[Math.max(index, nextIndex)];
  return document.slice(0, first.start) + document.slice(second.start, second.end) +
    document.slice(first.end, second.start) + document.slice(first.start, first.end) +
    document.slice(second.end);
}
