# Local development preview

Start the backend using the liveness-only command in `../backend/README.md`,
then run `npm install` and `npm run dev` in this directory. Open
`http://127.0.0.1:5173/`. Vite forwards `/api` to `http://127.0.0.1:8000`;
verify the connection at `/api/v1/health`.

The default backend is liveness-only. Authenticated features require the
configured HTTPS origin, TLS boundary, identity provider and database described
in the backend documentation. The development proxy is not a production
deployment or an authentication bypass.

## Sample node catalog

The Workflows screen can request the owner-only sample-validation node catalog
and display its port and configuration schemas. The catalog is read-only: it
does not add nodes, authorize execution or indicate model readiness. Requests
use the existing session boundary; denial clears protected workflow state. The
backend contract is in [the workflow specification](../docs/SPEC-workflow-runtime.md#sample-validation-node-catalog).

## Workflow editor handoff

The draft editor can initialize empty drafts, add and inspect node JSON, reorder
nodes, remove unconnected nodes, and add, edit or remove readable connections.
Node and connection edits remain local until the existing version-checked save.
Editing a node preserves its ID; editing a connection with extra fields requires
the JSON editor. The backend validates node types, ports and graph shape; an
edit or successful save does not imply validity or execution readiness.

After the Workflows section is opened, the editor stays mounted but hidden
across section changes. Unsaved draft changes and partially entered node and
connection fields request a browser warning on unload; browser behavior varies
and this is not crash recovery. Pending fields must be added or cleared before
switching drafts or editing, saving or validating the document. Hidden workflow
components can complete outstanding requests; authorization failures still
clear protected content. Live authenticated and screen-reader verification
remain outstanding. See [the task tracker](../tasks/todo.md) for merge and
review status.
