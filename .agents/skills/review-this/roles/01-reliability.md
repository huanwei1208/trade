# Judge 1: Reliability & Resilience

Audit for: data loss prevention, error handling, retry logic, idempotency, crash
recovery, concurrent-execution safety, locking, atomicity, stale reads, partial
failure semantics, silent corruption, WAL/checkpoint, backpressure.

## Checklist

- Retries: which exceptions are retried? Are deterministic failures (schema
  errors, auth errors, contract violations) incorrectly retried?
- Are there per-process in-memory buffers that lose data on crash? Is there a
  WAL or sentinel?
- Read-modify-write sequences (e.g. load parquet, concat, write) — are they
  guarded by cross-process locks or can two concurrent runs clobber each other?
- Does a partial success (1 of N assets failed) get mis-reported as total
  success? Are downstream gates blocked on critical-asset failure?
- Fallback chains (e.g. primary → backup source): do they actually trigger on
  the failures they are designed for (empty responses, not just exceptions)?
- Error classifications: are connection/timeouts distinguished from bad-data?
- Idempotency: if an event/job is replayed after crash, does it double-run or
  double-write? Is there a dedup key?
- Locks: are exclusive locks held for the entire critical section? Are shared
  locks correctly downgraded?
- Is corrupted input quarantined, or silently replaced with default values?
- Startup recovery (replay pending events, rebuild watermarks) — does it cover
  all in-flight state?

## Rate each finding CRIT/HIGH/MED/LOW with file:line.
