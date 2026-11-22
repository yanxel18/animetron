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
nodes and add a connection through named ID/port fields. Node and connection
insertion preserve the existing JSON text and remain local until the existing
version-checked save. The backend validates node types, ports and graph shape;
an insertion or successful save does not imply validity or execution readiness.
The connection editor is stacked on PR #125 and is not complete until its PR,
review and required checks are resolved. A backend-driven palette, connection
discovery and live authenticated end-to-end verification remain outstanding.
