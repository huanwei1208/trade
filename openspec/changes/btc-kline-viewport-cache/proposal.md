## Why

The BTC Market K-line now loads the full available history, which is useful for
manual historical inspection but too broad as the initial view. Users need the
chart to open on the most recent market context while keeping older candles
available through normal chart zoom and scroll.

The viewport is presentation state only. It should not reintroduce request
windows, range selectors, backend filtering, or any change to Observatory data,
publication, or trading semantics.

## What Changes

- Open the selected-channel BTC candlestick chart on the most recent roughly
  one month of available data when there is no compatible saved viewport.
- Keep the complete series loaded in the browser chart so mouse wheel zoom,
  drag scroll, touch pan, Fit, and latest navigation can still reach historical
  data.
- Persist the last visible chart time range in localStorage with a versioned,
  identity-bound cache so a reload restores the user's last BTC chart position
  when it still matches the current asset and display timeframe.
- Safely ignore malformed, stale, incompatible, or out-of-series cached
  viewports and fall back to the deterministic recent-window default.

## Non-Goals

- No API, CLI, DB, parquet, data ingestion, trading decision, recommendation, or
  research contract change.
- No backend `from`/`to` request bounds and no restoration of the removed range
  selector.
- No persistent caching of Observatory payloads, prices, evidence, trust, or
  publication state.
- No change to lifecycle labels such as published or unpublished.

## Affected Contracts

- **Web presentation:** `ExchangeKlinePanel` owns browser-local viewport policy
  and cache validation; `ExchangeKlineChart` applies the resulting logical
  visible range and emits user range changes. All loaded candles remain
  available to the chart.
- **Browser storage:** add an internal versioned localStorage record for the
  visible K-line range. Invalid records are discarded by behavior, not by
  mutating external data.
- **URL/API/data:** unchanged. Existing `obsTimeframe`, `obsChart`, channel, and
  date evidence behavior remain compatible.

## Rollout and Rollback

Rollout is frontend-only and additive. Rollback is a source revert of the
viewport helper and chart wiring. Existing localStorage cache values become
ignored if the key or version is removed, with no data migration required.

## Validation

- Add focused helper and component tests for default recent-month viewport,
  valid cache restore, invalid cache fallback, visible-range persistence, Fit,
  and latest-window controls.
- Run focused Vitest coverage for the K-line chart, frontend typecheck/build,
  `./trade dev check --show-plan`, `./trade dev check`, and `git diff --check`.
