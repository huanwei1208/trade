# Judge 2: Performance & Scalability

Audit for: throughput, QPS control, memory, parquet I/O patterns, event bus
congestion, thread-pool sizing and routing, backpressure, connection pooling,
N+1 queries, what breaks when asset count grows 10×.

## Checklist

- Ingestion: token bucket correctly isolated? Any global rate limit that
  bottlenecks? Concurrency limits vs I/O wait time.
- Parquet writes: full-file rewrite on every sync? Append vs compact pattern?
  Atomic temp-file rename in place? Double-reads (load existing for watermark
  then again for merge)?
- Buffer design: is the buffer lock per-asset or global? Can one slow flush
  block all assets? Buffer size vs flush timeout.
- Event bus: channel routing matches the work type? (network I/O vs CPU-heavy
  NLP vs latency-sensitive signals vs blocking I/O). Bounded queues? Drop
  policy? Backpressure?
- DB connections: per-request churn vs pooled? Long-lived connection in SSE
  loops? Global locks serializing concurrent reads that SQLite WAL could
  parallelize?
- Pandas patterns: full read of parquet when only max-date (watermark) is
  needed? DuckDB pushdown used? concat+dedup in hot loops?
- Web: SSE polling frequency, repeated SQL queries, N+1 parquet reads on list
  pages, snapshot caching.
- Index coverage on hot SQL paths.
- Vectorized operations vs row-wise apply() on DataFrames.

## What breaks at 10× scale?

Identify the first bottleneck if the tracked universe grows from 7 to 70/500
assets, or news firehose arrives at 100 articles/sec.

## Rate each finding CRIT/HIGH/MED/LOW with file:line.
