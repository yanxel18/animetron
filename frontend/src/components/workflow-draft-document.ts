export type WorkflowNodeOrderItem = {
  id: string;
  type: string;
};

type ParsedWorkflowDraft = {
  document: Record<string, unknown>;
  nodes: Record<string, unknown>[];
  order: WorkflowNodeOrderItem[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasUniqueObjectKeys(json: string): boolean {
  let index = 0;
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

  function readValue(): boolean {
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
        if (!readValue()) return false;
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
      skipWhitespace();
      if (json[index] === "]") {
        index += 1;
        return true;
      }
      while (index < json.length) {
        if (!readValue()) return false;
        skipWhitespace();
        if (json[index] === "]") {
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
    // JSON.parse accepts duplicate keys, but stringifying them would silently discard data.
    if (!readValue()) return false;
    skipWhitespace();
    return index === json.length;
  } catch {
    return false;
  }
}

function parseWorkflowDraft(document: string): ParsedWorkflowDraft | null {
  let value: unknown;
  try {
    value = JSON.parse(document);
  } catch {
    return null;
  }
  if (!hasUniqueObjectKeys(document) || !isRecord(value) || value.schemaVersion !== 1 ||
    typeof value.revision !== "string" || !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges)) {
    return null;
  }

  const nodes: Record<string, unknown>[] = [];
  const order: WorkflowNodeOrderItem[] = [];
  const ids = new Set<string>();
  for (const candidate of value.nodes) {
    if (!isRecord(candidate) || typeof candidate.id !== "string" ||
      candidate.id.length === 0 || typeof candidate.type !== "string" ||
      !isRecord(candidate.config) || ids.has(candidate.id)) {
      return null;
    }
    ids.add(candidate.id);
    nodes.push(candidate);
    order.push({ id: candidate.id, type: candidate.type });
  }
  return { document: value, nodes, order };
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

  const index = parsed.nodes.findIndex((node) => node.id === nodeId);
  const nextIndex = index + (direction === "up" ? -1 : 1);
  if (index < 0 || nextIndex < 0 || nextIndex >= parsed.nodes.length) return null;

  const nodes = [...parsed.nodes];
  [nodes[index], nodes[nextIndex]] = [nodes[nextIndex], nodes[index]];
  return JSON.stringify({ ...parsed.document, nodes }, null, 2);
}
