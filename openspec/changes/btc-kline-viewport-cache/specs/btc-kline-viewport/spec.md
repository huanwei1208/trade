## ADDED Requirements

### Requirement: BTC K-line opens on recent context while retaining history

The BTC Market K-line SHALL load the full selected-channel series available to
the frontend chart while opening on a recent visible range by default. The
visible range is presentation state and SHALL NOT constrain Observatory API
requests, data evidence, publication state, or formal/trading semantics.

#### Scenario: No compatible viewport cache exists

- **WHEN** the selected-channel K-line receives more than roughly one month of
  daily data and no compatible saved viewport exists
- **THEN** the chart applies a visible time range ending at the latest available
  candle and beginning roughly one month earlier
- **AND THEN** older candles remain loaded and reachable through chart zoom,
  scroll, pan, or Fit

#### Scenario: Compatible viewport cache exists

- **WHEN** the user reloads the same asset and display timeframe after zooming
  or scrolling the K-line
- **THEN** the chart restores the last saved visible time range when it is valid
  and overlaps the current series
- **AND THEN** the restore does not alter the selected channel, selected date,
  Date Evidence request, or loaded series data

#### Scenario: Viewport cache is invalid or incompatible

- **WHEN** the saved viewport is malformed, stale-versioned, asset-mismatched,
  timeframe-mismatched, reversed, or outside the current series
- **THEN** the chart ignores it and applies the recent visible range default
- **AND THEN** the user receives a normal chart rather than an error or empty
  visible plot caused by browser storage

#### Scenario: User navigates the K-line viewport

- **WHEN** the user zooms, scrolls, pans, taps Fit, or taps Newest
- **THEN** the chart updates only the visible viewport and preserves all loaded
  K-line data
- **AND THEN** the last visible time range is persisted in localStorage when the
  browser allows it
