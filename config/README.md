# Config Layout

## Entry files

- `config/config.yaml`: C++ engine runtime config.
- `config/defaults.json`: Python CLI defaults (global), including sentiment defaults.

## Feed catalog

- `config/feeds/rss.json`: RSS feed index and quality metadata.
- `config/feeds/gdelt.json`: GDELT historical backfill channels.
- `config/feeds/backfill_priority.json`: cross-channel backfill priority weights.

## Module files

- `config/modules/security.yaml`
- `config/modules/storage.yaml`
- `config/modules/sentiment.yaml`

## Compatibility notes

- Active code paths read only `config/feeds/*.json`.
