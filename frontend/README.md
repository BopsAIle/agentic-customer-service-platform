# Operator Console Frontend

Before changing this frontend, read:

- [`../docs/frontend-design-guidelines.md`](../docs/frontend-design-guidelines.md) for the visual and interaction system.
- [`../skills/ui-ux-pro-max/SKILL.md`](../skills/ui-ux-pro-max/SKILL.md) for the project-local design workflow.

The console uses React, TypeScript, Vite, Tailwind CSS, and npm. Keep frontend refinements within this stack unless a dependency is clearly necessary and explicitly approved. Do not change backend contracts as part of a UX refinement.

Install dependencies reproducibly with `npm ci`. Before submitting a change, run
`npm run typecheck`, `npm run lint`, `npm test`, and `npm run build`.

The production nginx image runs unprivileged on port 8080. It applies security headers, serves
fingerprinted `/assets/` files with immutable caching, keeps HTML and proxied API responses
revalidatable or non-cacheable, and routes unknown client paths through the SPA entry point.

## Local authenticated development

Create the repository-root environment file first, then start the backend and Vite:

```bash
cp .env.example .env
uv sync --frozen
make migrate
make seed
make dev
```

```bash
cd frontend
npm ci
npm run dev
```

Vite reads `LOCAL_DEMO_AUTH_TOKEN` from the root `.env` and injects it only for the explicitly
development/demo console. The API client retains it in module memory, centrally attaches the
Bearer header, and does not write it to localStorage or include it in inspector projections. Set
`VITE_BACKEND_TARGET` to override the default `http://localhost:8000` proxy destination. The proxy
covers `/agent`, `/ui`, `/customers`, `/orders`, `/tickets`, `/memories`, `/escalations`, `/health`,
and `/ready` without changing frontend API contracts.

For the container workflow, run `cp .env.example .env` and `docker compose up --build` from the
repository root, then open <http://localhost:5173>. nginx proxies the same API routes to the backend
and explicitly forwards `Authorization` while retaining the existing CSP and security headers.

The Operator Console memory panel receives lifecycle metadata only. The `/ui/memory` client type
does not include persisted memory body text, and the panel displays type, normalized key, source,
status, timestamps, and expiration. Memory content remains available internally to the
agent runtime according to memory policy; the console has no reveal path.

`local-demo-support-token` is deterministic, public localhost/demo configuration. It must never be
used as a production credential. The production Compose overlay builds the console without this
token; a real deployment must integrate its own authenticated session/token acquisition mechanism.
