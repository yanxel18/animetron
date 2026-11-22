import { useEffect, useMemo, useRef, useState } from "react";
import { appendWorkflowNode, moveWorkflowNode, readWorkflowNodeOrder } from "./workflow-draft-document";

type MoveDirection = "up" | "down";

type WorkflowNodeOrderProps = {
  document: string;
  disabled: boolean;
  onDocumentChange: (value: string) => void;
};

export function WorkflowNodeOrder({
  document, disabled, onDocumentChange,
}: WorkflowNodeOrderProps) {
  const nodeOrder = useMemo(() => readWorkflowNodeOrder(document), [document]);
  const nodeMoveButtons = useRef(new Map<string, Partial<Record<MoveDirection, HTMLButtonElement>>>());
  const focusAfterMove = useRef<{ id: string; direction: MoveDirection } | null>(null);
  const addedNode = useRef(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [nodeText, setNodeText] = useState("");
  const [nodeError, setNodeError] = useState<string | null>(null);
  const [nodeNotice, setNodeNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!addedNode.current) setNodeNotice(null);
    addedNode.current = false;
    const pending = focusAfterMove.current;
    if (pending) {
      nodeMoveButtons.current.get(pending.id)?.[pending.direction]?.focus();
    } else {
      setNotice(null);
    }
    focusAfterMove.current = null;
  }, [document]);

  function moveNode(id: string, direction: MoveDirection) {
    const updatedDocument = moveWorkflowNode(document, id, direction);
    const updatedOrder = updatedDocument ? readWorkflowNodeOrder(updatedDocument) : null;
    const position = updatedOrder?.findIndex((node) => node.id === id) ?? -1;
    if (!updatedDocument || !updatedOrder || position < 0) return;

    focusAfterMove.current = { id, direction: direction === "up" ? "down" : "up" };
    setNotice(`Moved ${id} to position ${position + 1} of ${updatedOrder.length}.`);
    onDocumentChange(updatedDocument);
  }

  return <section className="workflow-node-order" aria-labelledby="workflow-node-order-title">
    <h3 id="workflow-node-order-title">Node order</h3>
    <p>Use the buttons to reorder nodes. Changes stay local until the draft is saved.</p>
    {nodeOrder !== null && <div>
      <label htmlFor="workflow-new-node">Node JSON</label>
      <p id="workflow-new-node-help">Enter one node object with an ID, type and config. Validate the saved draft to check supported types and connections.</p>
      <textarea id="workflow-new-node" className="workflow-json workflow-json-editor" value={nodeText}
        aria-describedby="workflow-new-node-help" disabled={disabled} maxLength={32768}
        onChange={(event) => { setNodeText(event.target.value); setNodeError(null); setNodeNotice(null); }} />
      <button className="button button--secondary" type="button" disabled={disabled} onClick={() => {
        const updated = appendWorkflowNode(document, nodeText);
        if (!updated) {
          setNodeError("Cannot add this node. Check the JSON, unique ID, node fields and draft size.");
          return;
        }
        addedNode.current = true;
        onDocumentChange(updated);
        setNodeText("");
        setNodeError(null);
        setNodeNotice("Node added locally. Save the draft to keep it.");
      }}>Add node</button>
      {nodeError && <p role="alert">{nodeError}</p>}
      {nodeNotice && <p role="status">{nodeNotice}</p>}
    </div>}
    {nodeOrder === null ? (
      <p role="note">Node ordering is unavailable because this draft does not contain a readable workflow node list. You can still edit the JSON directly.</p>
    ) : nodeOrder.length === 0 ? (
      <p role="note">This draft has no nodes to reorder.</p>
    ) : (
      <ol className="workflow-node-order-list" aria-label="Workflow node order">
        {nodeOrder.map((node, index) => (
          <li className="workflow-node-order-item" key={node.id}>
            <div className="workflow-node-order-details">
              <strong>{node.type || "Unspecified node type"}</strong>
              <code>{node.id}</code>
            </div>
            <div className="workflow-node-order-actions">
              <button className="button button--secondary" type="button"
                aria-label={`Move ${node.id} up`} disabled={index === 0 || disabled}
                ref={(element) => {
                  const buttons = nodeMoveButtons.current.get(node.id) ?? {};
                  if (element) {
                    buttons.up = element;
                    nodeMoveButtons.current.set(node.id, buttons);
                  } else {
                    delete buttons.up;
                    if (buttons.down) nodeMoveButtons.current.set(node.id, buttons);
                    else nodeMoveButtons.current.delete(node.id);
                  }
                }}
                onClick={() => moveNode(node.id, "up")}>Move up</button>
              <button className="button button--secondary" type="button"
                aria-label={`Move ${node.id} down`}
                disabled={index === nodeOrder.length - 1 || disabled}
                ref={(element) => {
                  const buttons = nodeMoveButtons.current.get(node.id) ?? {};
                  if (element) {
                    buttons.down = element;
                    nodeMoveButtons.current.set(node.id, buttons);
                  } else {
                    delete buttons.down;
                    if (buttons.up) nodeMoveButtons.current.set(node.id, buttons);
                    else nodeMoveButtons.current.delete(node.id);
                  }
                }}
                onClick={() => moveNode(node.id, "down")}>Move down</button>
            </div>
          </li>
        ))}
      </ol>
    )}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
