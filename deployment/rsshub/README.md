# Self-hosted RSSHub (for sentiment pipeline)

## Start

```bash
cd deployment/rsshub
cp .env.example .env
docker compose up -d
```

Default endpoint:

- `http://127.0.0.1:1200`

Quick check:

```bash
curl -I http://127.0.0.1:1200/cls/telegraph
```

## Optimization notes

This compose setup is tuned for stability:

- Redis-backed cache (`CACHE_TYPE=redis`) instead of in-memory cache
- Persistent Redis volume (`rsshub_redis_data`) to survive restarts
- Container CPU/memory limits to avoid host contention
- Docker log rotation to avoid disk bloat

Tune via `.env`:

- `RSSHUB_MEM_LIMIT`, `RSSHUB_CPUS`, `RSSHUB_SHM_SIZE`
- `RSSHUB_CACHE_EXPIRE`
- `REDIS_MEM_LIMIT`, `REDIS_CPUS`, `REDIS_MAX_MEMORY`

Inspect status:

```bash
cd deployment/rsshub
docker compose ps
docker compose logs -f rsshub
docker compose logs -f redis
```

## Use in this project

Run sentiment with local RSSHub:

```bash
cd python
uv run python -m scripts.run_sentiment --date 2026-03-04 --dry-run --rsshub-base-url http://127.0.0.1:1200
```

Or set env once for current shell:

```bash
export TRADE_RSSHUB_BASE_URL=http://127.0.0.1:1200
cd python
uv run python -m scripts.run_sentiment --date 2026-03-04 --dry-run
```

## Stop

```bash
cd deployment/rsshub
docker compose down
```
