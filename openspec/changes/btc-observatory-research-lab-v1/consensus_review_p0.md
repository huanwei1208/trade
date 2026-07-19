# WP0 Consensus Review — P0 Closure

The plan mandates a `review-this` six-role consensus review for medium/large
changes with all P0 findings closed before implementation. This change was
reviewed against the six lenses (reliability, performance, architecture,
data-quality, observability, news-sentiment). Findings and closures:

| # | Lens | P0 finding | Closure in this change |
| --- | --- | --- | --- |
| 1 | reliability | Read path could silently fall back to another artifact on hash mismatch | Frozen: integrity mismatch returns 409 fail-closed; `snapshot-semantics` "Reads never trigger writes" scenario |
| 2 | reliability | Catalog could be written during a GET | Frozen: `CATALOG_STALE` on stale read; Catalog only updated by explicit CLI/Operations |
| 3 | data-quality | Single `current` collapses candidate vs formal vs observed | Orthogonal channels + state axes; composite never merged |
| 4 | data-quality | Legacy manifests lack stage times; risk of mtime guessing | Versioned legacy adapter, `LEGACY_TIME_UNPROVEN`, never mtime; `PIT_NOT_PROVEN` before earliest receipt |
| 5 | architecture | Second source of truth / dual current authority for H1 | Catalog is a projection; research adapter mirrors the single existing `activate_run` authority |
| 6 | architecture | `app.py` growth | Router lives in `trade_web/backend/observatory/`; `app.py` does minimal registration |
| 7 | observability | Purpose fitness returning a bare boolean hides blockers | Frozen `{allowed,status,reason_codes,evidence_refs}` contract |
| 8 | performance | Per-request full parquet/run scans | Catalog summary reads; context does 0 parquet opens; frozen benchmark envelope |
| 9 | news-sentiment | Risk of a single sentiment score / causal narrative | Non-goal; events express temporal adjacency only, no causal claims |
| 10 | reliability | Latest Attempt promise unbackable without attempt receipts | Downgraded to Latest Completed Staged Run; attempt receipts deferred with recorded task |

All P0 findings above are closed by frozen contracts in this change. No open P0
remains blocking implementation.

## Fixture inventory (frozen relations)

Fixtures live under `tests/observatory/fixtures/` and are built by a factory
(`tests/observatory/fixtures.py`) so relations are explicit and frozen:

- `formal_run`: published release, watermark F, `data_readiness=ready`.
- `candidate_run`: staged, `data_readiness=degraded`, watermark C > F (proves
  `observed_watermark > formal_watermark`).
- `observed_only_run`: primary-success/shadow-partial, watermark O >= C.
- `invalid_run`: `data_readiness=invalid` with a rendering blocker (must not enter
  composite).
- `empty_run`: 0 canonical rows (must not move Observed).
- `revised_pair`: two runs sharing dates with a later revision (PIT isolation).
- `legacy_run`: manifest without stage times (legacy adapter + `LEGACY_TIME_UNPROVEN`).

These frozen relations back the selector truth table, composite layering, PIT
isolation, and error-semantics tests across WP1-WP9.
