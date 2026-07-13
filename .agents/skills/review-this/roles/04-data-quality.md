# Judge 4: Data Quality & Validation

Audit for: OHLCV validation, outlier detection, timestamp/timezone correctness,
cross-source reconciliation, look-ahead bias, schema evolution, gap detection,
silent corruption vectors, missing value policy.

## Checklist

- OHLC structural invariants enforced (high >= open/close/low, low <= ...)?
  Positive prices/volume? Monotonic dates? No duplicate timestamps?
- Outlier detection: MAD-based or fixed-threshold return gates? Are alt-crypto,
  FX, commodity subject to the same rigor as the flagship asset?
- Volume validation: zero/negative volume rows?
- Timezone alignment: are all timestamps normalized to UTC? Any naive datetime
  mixing between Asia/Shanghai trading days and UTC crypto?
- Cross-source reconciliation: is there a third independent source (not two
  sources aliased as three)? How are disagreements resolved (quarantine vs
  last-write-wins)?
- Look-ahead bias: watermark uses strict `>` or `>=`? `drop_duplicates` uses
  keep="first" (conservative) or keep="last" (revisions applied)? Are future
  revisions only caught if a full refresh window covers them?
- Retroactive revisions: how far back does a full refetch look? Can a silently
  revised bar from 90 days ago be detected?
- Missing values: are NaNs filled with zeros (poison), forward-filled (must
  be flagged as synthetic), or left as NaN?
- Synthetic data: does weekend/Holiday ffill write bars marked with an
  `observed` boolean so downstream features know what's real vs fabricated?
- Schema evolution: is schema_version checked at read time? Missing columns
  cause error or silent zero-fill?
- Sentiment/text data: date parse fallback to "now" (poisoned timestamps)?
  Range validation (Fear&Greed 0-100)? URL deduplication?
- Gaps: proactive scanner (expected vs actual calendar) vs repair-driven only?
  24/7 crypto gaps vs trading-calendar-aware A-share gaps distinguished?
- Quarantine: when bad rows are dropped, is a persistent data_gaps row written?

## Silent corruption test

Answer: "What silent data corruption could happen today without detection?"
List each path with file:line and detection gap.

## Rate each finding CRIT/HIGH/MED/LOW with file:line.
