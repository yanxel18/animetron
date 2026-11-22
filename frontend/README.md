# Local development preview

Start the backend using the liveness-only command in `../backend/README.md`,
then run `npm install` and `npm run dev` in this directory. Open
`http://127.0.0.1:5173/`. The Vite development server forwards `/api` requests
to `http://127.0.0.1:8000`; verify the connection at `/api/v1/health`.

The default backend is liveness-only. Authenticated features require the
configured HTTPS origin, TLS boundary, identity provider and database described
in the backend documentation. The development proxy is not a production
deployment or an authentication bypass.
