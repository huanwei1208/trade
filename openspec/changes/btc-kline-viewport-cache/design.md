## Context

The BTC Observatory Market chart now has enough local OHLCV history that a full
fit view opens too compressed for day-to-day inspection. The user can already
manually zoom and pan the Lightweight Charts surface, so the missing behavior
is viewport policy: default the view to the recent market context, keep the full
series loaded, and remember where the user last inspected the chart.

This is presentation state only. It must not reintroduce backend range filters,
change Date Evidence semantics, alter publication labels, or affect any trading
or research contract.

## Design Quality Brief

### Requirements and acceptance

The BTC selected-channel K-line opens on the most recent available context when
there is no compatible saved viewport. For daily data the default window is
roughly one month; display aggregates use similarly small recent windows so the
same control remains useful after timeframe changes. Older candles remain in
the loaded chart model and are reachable through ordinary wheel zoom, drag pan,
touch pan, Fit, and Newest controls.

Acceptance requires a valid localStorage viewport to restore only when it
matches the current asset identity and display timeframe, maps to dates present
in the current aggregated series, and has an ordered date range. Invalid,
malformed, stale-versioned, incompatible, or out-of-series records fall back to
the deterministic recent-window default without an error surface.

### Ownership and boundaries

`trade_web/frontend/src/components/observatory/ExchangeKlinePanel.tsx` owns the
viewport policy and browser-local cache. It already owns conversion from the
server daily series into the chart model and is outside the lazy chart chunk, so
placing localStorage parsing there keeps the renderer bundle small and prevents
storage concerns from leaking into the chart runtime.

`ExchangeKlineChart.tsx` owns only chart-runtime application of a logical
visible range and emits logical range changes through a typed callback. It does
not read localStorage, choose date policy, or filter the loaded model.

### Data and state invariants

The full selected-channel series remains the model authority. The viewport is a
pair of logical indexes derived from existing model dates; it never deletes
candles, changes adapter diagnostics, mutates selected date, or changes Date
Evidence requests. The cache identity is bound to asset id or symbol plus the
display timeframe, and the cache payload stores date strings rather than raw
logical indexes so stale chart geometry cannot silently select a different
history range after aggregation changes.

All storage access is best-effort. Browser storage failures, denied access, or
bad records return `null` and the chart continues with a normal visible range.

### Contracts and compatibility

No API route, request parameter, response payload, URL parameter, database,
parquet layout, or engine interface changes. Existing `obsTimeframe`, selected
date, channel, knowledge, and Date Evidence behavior remain compatible.

The new browser-local cache key is internal UI state. It is versioned and
identity-bound, so rollback can leave old values unused without migration. Fit
continues to show all loaded history, while Newest applies the recent cached or
default viewport ending at the latest candle.

### Failure and recovery

Malformed cache values, reversed ranges, missing dates, incompatible asset or
timeframe records, and localStorage exceptions are handled by ignoring the cache
and using the recent default. If the chart runtime fails while applying a range,
the existing renderer failure state is used and the user can retry or open the
Compare view.

The chart must never render an empty or misleading viewport because of storage.
If no recent or cached range can be derived, the chart falls back to the
existing fit-all behavior.

### Performance and capacity

The data volume does not grow. The chart still receives the same in-memory model
and Lightweight Charts handles pan and zoom against loaded series data. Cache
parsing is one small localStorage read per model/timeframe identity and one
small write per visible range callback. Moving cache logic to the panel keeps
the lazy chart bundle within the existing gzip budget.

### Observability and operations

No backend metric or operational workflow is added because the behavior is
browser-local presentation state. Failures are intentionally silent unless the
chart runtime itself fails, in which case the existing safe renderer error codes
remain the observable state in tests and UI.

### Validation strategy

Focused Vitest coverage exercises the default recent window, valid cache
restore, incompatible cache fallback, logical visible range application, owner
callback wiring, and persistence. Frontend typecheck and build validate the
typed React boundary and the Observatory bundle budget. Repository checks and
`git diff --check` cover shared quality gates.

### Alternatives and trade-offs

The first approach placed storage helpers inside the lazy chart component. That
kept behavior close to the runtime but exceeded the strict chart gzip budget.
The selected approach stores date-policy logic in `ExchangeKlinePanel` and
leaves `ExchangeKlineChart` as a minimal logical-range bridge.

Storing logical indexes would be smaller, but dates are safer across aggregation
and data refreshes. A URL parameter was rejected because this is a personal
viewport preference, not a shareable market evidence selector.

### Rollout and rollback

Rollout is frontend-only and additive. Rollback is a source revert of the panel
cache helpers and chart visible-range props. Existing localStorage values become
ignored if the key or version is removed; no data migration, cache cleanup, or
backend rollback is required.
