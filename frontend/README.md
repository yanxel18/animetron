# Local development preview

Start the backend using the liveness-only command in `../backend/README.md`,
then run `npm install` and `npm run dev` in this directory. Open
`http://127.0.0.1:5173/`. The Vite development server forwards `/api` requests
to `http://127.0.0.1:8000`; verify the connection at `/api/v1/health`.

The default backend is liveness-only. Authenticated features require the
configured HTTPS origin, TLS boundary, identity provider and database described
in the backend documentation. The development proxy is not a production
deployment or an authentication bypass.

## Workflow editor handoff

The owner can initialize an empty draft, enter a node JSON object, reorder
nodes, remove unconnected nodes, and add a connection through named ID/port fields. Node and connection
insertion preserve the existing JSON text and remain local until the existing
version-checked save. The backend validates node types, ports and graph shape;
an insertion or successful save does not imply validity or execution readiness.
The node inspector shows the exact current-draft node JSON, including unsaved
changes; it does not validate the node. This inspector slice is stacked on #132.
An existing node can be edited as JSON without changing its ID; the update is
local until saved and still requires backend validation. This edit slice is
stacked on #134.
The connection editor is stacked on the node-boundary fix in PR #127 and is
not complete until its PR, review and required checks are resolved. A backend-driven palette, connection
discovery and live authenticated end-to-end verification remain outstanding.
Node removal is stacked on PR #128; it refuses removal if an existing edge
references the node or has unreadable endpoints. The connection list can remove
readable edges, and falls back to direct JSON editing for ambiguous lists.
Connection removal is stacked on PR #129. Removal remains local until saved.

After the Workflows section has been opened, the editor stays mounted but hidden
when switching sections, preserving its in-memory draft. Unsaved draft-document
changes request a browser warning on reload or close; browser behavior varies,
and this does not restore data after a crash. Partially entered node and
connection fields also trigger the warning and must be added or cleared before
switching drafts or editing, saving or validating the document. Hidden workflow components
remain mounted and can complete outstanding requests; authorization failures
still clear protected content. The pending-input protection is stacked on PR #131.
