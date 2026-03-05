# Trade Intelligence 2.0 Architecture

## Goals

Redesign the data layer so it is unified, queryable, and extensible, allowing the compute
layer (signals, window_scorer, morning_brief) to grow naturally on top.

**Pain points addressed:**

- Data code scattered across `data/`, `intelligence/`, `scripts/` with inconsistent schemas
- No unified data model: kline / fund_flow / news / cross_asset each use different storage
- Pipeline state managed by JSON watermark files — impossible to query coverage gaps
- `run_sentiment.py::main()` was 406 lines with 20+ CLI flags
- Compute layer built on a fragile data foundation

---

## Core Principles

1. **Single home for all data code** — `trade_py/data/` owns every data source
2. **Source Plugin Protocol** — add a new source by implementing one interface, nothing else changes
3. **DuckDB as pipeline state center** — replaces watermark JSON files; SQL-queryable coverage
4. **Silver incremental cache** — skip LLM re-analysis for already-processed `content_hash`
5. **Decoupled compute layer** — signals/window_scorer/morning_brief read only from Gold layer

---

## Directory Structure

```
python/trade_py/
├── data/
│   ├── source.py                  # DataSource protocol + RawRecord dataclass
│   ├── news/
│   │   ├── rss_source.py          # migrated from intelligence/rss_fetcher.py
│   │   ├── gdelt_source.py        # migrated from intelligence/backfill_fetcher.py
│   │   └── cls_source.py          # 财联社 (planned)
│   ├── market/
│   │   ├── kline_source.py
│   │   ├── fund_flow_source.py
│   │   └── cross_asset_source.py
│   └── pipeline/
│       ├── ingest.py              # Source → Bronze
│       ├── enrich.py              # Bronze → Silver (skip-if-processed)
│       └── aggregate.py           # Silver → Gold
│
├── db/
│   ├── pipeline_db.py             # DuckDB pipeline state (NEW)
│   └── instruments_db.py
│
├── intelligence/
│   ├── _utils.py                  # Shared helpers (meta scoring, html cleaning)
│   ├── claude_client.py
│   └── enricher.py                # LLM logic extracted from sentiment_pipeline.py
│
└── signals/
    ├── window_scorer.py
    └── cross_asset_signal.py

docs/
└── architecture-2.0.md
```

---

## Core Interfaces

### `data/source.py` — DataSource Protocol

```python
@dataclass
class RawRecord:
    source_id: str
    data_type: Literal["news", "price", "flow", "filing"]
    content_hash: str
    published_at: datetime
    title: str
    text: str
    url: str
    meta: dict

class DataSource(Protocol):
    source_id: str
    data_type: Literal["news", "price", "flow", "filing"]
    def fetch(self, since: datetime, until: datetime) -> list[RawRecord]: ...
    def health_check(self) -> dict: ...
```

### `db/pipeline_db.py` — DuckDB Pipeline State

Three tables replace all watermark JSON files:

```sql
-- One row per fetch run
CREATE TABLE ingest_runs (
    run_id         TEXT PRIMARY KEY,
    source_id      TEXT,
    fetched_at     TIMESTAMPTZ,
    date_range_start DATE,
    date_range_end   DATE,
    records_fetched  INT,
    records_new      INT,
    status           TEXT,  -- 'ok' | 'error'
    error            TEXT
);

-- Daily coverage matrix — query "which dates are missing?"
CREATE TABLE coverage (
    source_id    TEXT,
    data_date    DATE,
    record_count INT,
    last_updated TIMESTAMPTZ,
    PRIMARY KEY (source_id, data_date)
);

-- LLM enrichment status — skip-if-processed
CREATE TABLE enrichment_status (
    content_hash TEXT PRIMARY KEY,
    enriched_at  TIMESTAMPTZ,
    model        TEXT,
    status       TEXT   -- 'ok' | 'error'
);
```

### Silver Layer — New Fields (Phase 4)

| Field | Type | Description |
|-------|------|-------------|
| `policy_signal` | bool | Contains regulatory / policy signal |
| `event_chain` | str | Related historical event type (for knowledge graph) |
| `market_impact_scope` | str | `individual` / `sector` / `market` |
| `time_sensitivity` | str | `immediate` / `short_term` / `medium_long` |

---

## Simplified CLI (Phase 2+)

```bash
# Today, incremental (default)
python -m scripts.run_sentiment

# Backfill last 30 days
python -m scripts.run_sentiment --since 30d

# Coverage + source health report
python -m scripts.run_sentiment status

# List registered sources
python -m scripts.run_sentiment sources
```

---

## Implementation Phases

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 1** | Clean dead code; split `main()` into 4 functions | Done |
| **Phase 2** | DataSource protocol + DuckDB state + Silver incremental cache | Done |
| **Phase 3** | New sources (财联社, etc.) as plugins | Done |
| **Phase 4** | Richer Silver LLM fields | Done |
| **Phase 5** | Compute layer upgrade (window_scorer / morning_brief use Gold) | After Phase 4 |

---

## Files Removed in Phase 2

- `python/scripts/_paths.py` (dead wrapper over config_context)
- `python/trade_py/intelligence/rss_fetcher.py` → replaced by `data/news/rss_source.py`
- `python/trade_py/intelligence/backfill_fetcher.py` → replaced by `data/news/gdelt_source.py`
- `python/trade_py/intelligence/sentiment_pipeline.py` → split into `data/pipeline/` modules

---

## Validation

```bash
# Behaviour must be identical before and after each phase:
python -m scripts.run_sentiment --date 2026-03-04 --dry-run > before.log
# ... apply changes ...
python -m scripts.run_sentiment --date 2026-03-04 --dry-run > after.log
diff before.log after.log
```
