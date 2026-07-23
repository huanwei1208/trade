# Frozen Identity Map (WP0)

Status: FROZEN in M0. Downstream WPs must not redefine these.

## Asset identity

| Field | Value |
| --- | --- |
| asset_id | `crypto.BTC` |
| display_symbol | `BTC` |
| asset contract id | `btc-data-v1` (from manifest `contract_version`) |
| canonical file (compat view) | `data/market/crypto/btc.parquet` (lowercase) |
| current pointer (accelerator) | `data/market/crypto/btc_current.json` |
| run root | `data/market/crypto/runs/btc/<run_id>/` |
| audit root | `data/market/crypto/audit/{publish,rollback}/` |

`display_symbol` MUST NOT be used as identity. The uppercase `BTC.parquet` path is
a defect; the resolver uses the lowercase canonical file and never guesses case.

## Provider identity

| Role | Provider | instrument | quote | interval | notes |
| --- | --- | --- | --- | --- | --- |
| primary | okx | `BTC-USDT` | `USDT` | `1Dutc` | canonical source; never fallback to shadow |
| shadow | binance | `BTCUSDT` | `USDT` | `1d` | cross-validation only; never mixed/averaged into primary |

CoinGecko / BTC-USD narrative is superseded (see proposal). Historical CoinGecko
schema, if it exists, is only readable through an explicit versioned read adapter
and must not be rewritten as Binance evidence.

## Fact-priority order (frozen)

1. contract version + artifact hash recorded in an immutable run manifest/receipt
2. current executable provider registry
3. merged later OpenSpec changes
4. older plan provider names and directory examples (lowest)

Catalog must not infer contracts from class names, deprecated aliases, filename
case, or old provider labels.

## H1 research identity (frozen)

| Field | Authority |
| --- | --- |
| current-selection authority | existing lifecycle `activate_run` + `persist_crypto_validation_outputs()` atomic writer |
| current pointer | `warehouse/ads/_crypto_validation_current.json` |
| run identity | `validation_run_id` |
| generation identity | `generation_id` |

The observatory research adapter mirrors these; it never creates a second current
pointer or a competing authority.
