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

function findNodeRanges(json: string): { ranges: { start: number; end: number }[]; end: number } | null {
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
        if (!readValue(depth + 1, depth === 0 && key === "nodes")) return false;
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
  const nodeRanges = findNodeRanges(document);
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
  const parsed = parseWorkflowDraft(document);
  const candidate = parseWorkflowDraft(`{"schemaVersion":1,"revision":"draft","nodes":[${node}],"edges":[]}`);
  if (!parsed || !candidate || candidate.order.length !== 1 ||
      parsed.order.some((item) => item.id === candidate.order[0].id)) return null;
  const insertion = `${parsed.order.length ? "," : ""}${node}`;
  const updated = document.slice(0, parsed.nodeArrayEnd) + insertion + document.slice(parsed.nodeArrayEnd);
  if (new TextEncoder().encode(updated).length > 32_768) return null;
  return updated;
}

export function readWorkflowNodeOrder(document: string): WorkflowNodeOrderItem[] | null {
  return parseWorkflowDraft(document)?.order ?? null;
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
