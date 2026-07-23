## ADDED Requirements

### Requirement: BTC K-line opens on recent context while retaining history

The BTC Market K-line SHALL load the full selected-channel series available to
the frontend chart while opening on a recent visible range by default. The
visible range is presentation state and SHALL NOT constrain Observatory API
requests, data evidence, publication state, or formal/trading semantics.

#### Scenario: No compatible viewport cache exists

- **WHEN** the selected-channel K-line receives more than one recent-window
  worth of rendered candles and no compatible saved viewport exists
- **THEN** the chart applies a visible time range ending at the latest available
  rendered candle and beginning at the configured recent-window start for the
  active display timeframe
- **AND THEN** older candles remain loaded and reachable through chart zoom,
  scroll, pan, or Fit

#### Scenario: Compatible viewport cache exists

- **WHEN** the user reloads the same market K-line identity after zooming or
  scrolling the K-line
- **THEN** the chart restores the last saved visible time range when it is valid
  for the same asset, provider, instrument, quote, source interval, lifecycle
  channel, publication state, knowledge mode, revision policy, and display
  timeframe
- **AND THEN** both cached endpoints map exactly to rendered display candles in
  the current chart model
- **AND THEN** the restore does not alter the selected channel, selected date,
  Date Evidence request, or loaded series data

#### Scenario: Viewport cache is invalid or incompatible

- **WHEN** the saved viewport is malformed, stale-versioned, asset-mismatched,
  source-mismatched, channel-mismatched, knowledge-mismatched,
  timeframe-mismatched, reversed, missing either endpoint, whitespace-only, or
  outside the current rendered series
- **THEN** the chart ignores it and applies the recent visible range default
- **AND THEN** the user receives a normal chart rather than an error or empty
  visible plot caused by browser storage

#### Scenario: User navigates the K-line viewport

- **WHEN** the user zooms, scrolls, pans, taps Fit, or taps Newest
- **THEN** the chart updates only the visible viewport and preserves all loaded
  K-line data
- **AND THEN** the last visible time range is persisted in localStorage when the
  browser allows it
- **AND THEN** persistence is coalesced and repeated storage failures do not
  block interaction or keep retrying during the same panel session
