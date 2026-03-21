# EBRT 17 - Kline Normalization And Artifact Paths

## Goal

Close two operational hygiene issues together:

- move generated `catboost_info` and `*.egg-info` output under `data/`
- normalize A-share daily kline storage so local rows no longer mix broken `prev_close`, fake turnover, and mixed adjustment segments

## Progress

- [x] locate root causes for root-level `catboost_info` and `trade_py.egg-info`
- [x] redirect future `egg_info` output into `data/`
- [x] redirect CatBoost training artifacts into `data/catboost_info`
- [x] confirm current root generated directories were moved out of repo root
- [x] identify kline root causes:
  - Tushare `pct_chg` was incorrectly stored as `turnover_rate`
  - `prev_close` was being overwritten from `shift(close)`
  - fallback/update paths could mix adjusted and unadjusted ranges
- [x] patch kline parsing to preserve source `prev_close` and merge real `daily_basic.turnover_rate`
- [ ] batch-repair local kline parquet history from Tushare
- [ ] rescan local parquet health after repair
- [ ] run final verification and commit
