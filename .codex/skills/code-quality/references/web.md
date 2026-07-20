# TypeScript, JavaScript, and React rules

- Keep TypeScript strict. Do not add `any`, non-null assertions, or ignore comments to
  bypass a model/API mismatch without a narrow documented reason.
- Parse external payloads at the API boundary; keep components on typed application
  models.
- Separate data fetching/state transitions from presentational components. Extract a
  hook or service when effects, retries, caching, and rendering become mixed.
- Handle loading, empty, stale, partial, error, and unavailable states explicitly.
- Cancel or ignore stale async work and avoid state updates after unmount.
- Preserve keyboard access, labels, focus order, and non-color-only status semantics.
- Avoid unnecessary render-time allocations and unbounded chart/table rendering.

Prettier owns formatting, ESLint owns lint, and TypeScript owns types. Run:

```bash
./trade dev check
npm --prefix trade_web/frontend run typecheck
npm --prefix trade_web/frontend run build
```

Add focused component/API contract tests when behavior changes. Do not treat a Vite
build alone as behavior coverage.
