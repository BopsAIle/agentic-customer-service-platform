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
