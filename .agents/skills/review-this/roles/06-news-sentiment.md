# Judge 6: News, Sentiment & Future Data Integration

## Review Scope
Review all text/alternative-data pipelines, their integration with the event bus,
feature materialization, and how easily new data types (news, social, macro,
alternative data) can be added.

## Checklist

### Pipeline layering (Bronze/Silver/Gold)
- [ ] Does Bronze (raw) deduplicate by content hash? Is it partitioned?
- [ ] Does Silver (enriched) carry sentiment, event type, confidence, entities, embeddings?
- [ ] Does Gold (aggregated) produce numeric per-symbol features suitable for model input?
- [ ] Is LLM used only as a fallback / high-confidence path (hybrid design)?
- [ ] Are base-rule factors always computed so the pipeline degrades gracefully without LLM?

### Event bus integration
- [ ] Are NLP/news topics routed to a dedicated pool (not shared with market data ingest)?
- [ ] Is there a priority/urgent lane vs bulk lane?
- [ ] Are there bounded queues with explicit drop/backpressure policy?
- [ ] Is there a dead-letter queue or failure tracking for enrichment jobs?
- [ ] Is `data.*.ingested` routed downstream to signal/model pool, not back to ingest?

### Data source quality
- [ ] Do all timestamp parsers fail closed (return None / drop record) rather than fallback to `datetime.now()`?
- [ ] Are free-tier rate limits respected per source?
- [ ] Is there source reliability weighting in the Gold aggregation?
- [ ] Are RSS/HTTP sources cached with ETag/Last-Modified to avoid redundant fetches?
- [ ] Is there URL-level deduplication across sources?

### Sentiment/numeric features
- [ ] Are sentiment scores in a defined range (e.g. [-1, 1]) with validation?
- [ ] Are categorical event types one-hot encoded or embedded?
- [ ] Is there a "volume" / "intensity" feature (number of articles, source count)?
- [ ] Is there cross-source confirmation weighting?
- [ ] Do features have proper NaN/unknown handling for days with no news?
- [ ] Are publication timestamps used (not scrape timestamps) to avoid look-ahead bias?

### Alternative data readiness (macro, social, on-chain)
- [ ] Is there a `RawRecord` or equivalent schema that's source-agnostic?
- [ ] Can new data types plug in without changing Bronze schema?
- [ ] Are there separate client base classes for HTTP/RSS/WebSocket sources?
- [ ] Is there a per-source config mechanism (rate limits, poll intervals, credentials)?

### Cost control
- [ ] Are LLM calls gated by confidence threshold or batch size?
- [ ] Are embeddings cached by content hash?
- [ ] Is there a clear separation between free-tier and paid data sources?
- [ ] Are retry/backoff policies configured to avoid runaway costs on errors?

## Scoring
Rate each area 1-10, then overall score.

## Report Format
```
## Findings
### (Strengths)
### (Issues with file:line references)

## Gaps for future asset classes
(List what would block adding equities news, macro series, on-chain data, etc.)

## Priority fixes
P0 / P1 / P2 with rationale
```
