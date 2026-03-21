# EBRT_16 — Data Storage Redesign（Paimon-Inspired）

## 背景与动机

`data/` 目录目前有 **381,550 个文件、3.8 GB**，其中 97% 来自 kline 的月级分区设计：

```
market/kline/
  2020-01/  000001_SZ.parquet (7KB)  000002_SZ.parquet ...
  2020-02/  000001_SZ.parquet (7KB)  000002_SZ.parquet ...
  ...（75 个月份目录 × ~4,900 symbols = 370,723 个文件）
```

**核心痛点：**

| 问题 | 根因 |
|------|------|
| 读取一个 symbol 的历史 = 75 次文件 I/O | 月级分区，每月一个小文件（16–23 行） |
| kline 磁盘 2.9GB，但实际数据只占 ~2% | parquet 固定开销（footer/schema/bloom filter）在小文件里占主体 |
| 无法快速知道"哪些 symbol 有哪些日期的数据" | 没有 manifest 索引，只能扫目录或查 SQLite |
| 目录结构感觉混乱，不便扩展 | 多个数据集命名/分区逻辑不一致 |

参照 Apache Paimon 的 **Compaction（L0 → L1 合并）+ Manifest 索引** 思路，核心改动是 kline 存储从"月级分区"改为"per-symbol 合并文件"，并为每个数据集增加轻量 `_manifest.json`。

---

## Paimon 概念映射

| Paimon 概念 | 采用？ | 在本系统的实现 |
|------------|:------:|--------------|
| Compaction（L0 小文件 → L1 大文件） | ✅ | 75 个月文件 → 1 个 per-symbol 全量文件 |
| Manifest 文件（数据集索引） | ✅ | `_manifest.json`：symbol → {last_date, rows, bytes} |
| Schema 定义 | ✅ 最小 | manifest 中 schema_version 字段 |
| Snapshot / 时间旅行 | ❌ | 过重；SQLite sync_state 已记录 watermark，数据可重拉 |
| Bucketing（hash 分桶） | ❌ | 单进程，无分布式并发写入需求 |
| Changelog / CDC | ❌ | 无行级变更追踪需求 |

---

## 改后目录布局

```
data/
├── market/
│   ├── kline/                          ← 核心变化
│   │   ├── _manifest.json              ← NEW: 全量索引（~200KB JSON）
│   │   ├── 000001_SZ.parquet           ← 全历史（原来 75 个月文件合一，~80KB）
│   │   ├── 000002_SZ.parquet
│   │   └── ...（~4,900 个文件）
│   ├── fund_flow/                      ← 保持不变（已是 per-symbol flat）
│   ├── fundamental/                    ← 保持不变（已是 per-symbol flat）
│   ├── northbound/daily.parquet        ← 保持不变
│   ├── cross_asset/                    ← 保持不变（3 个文件）
│   ├── macro/                          ← 保持不变（4 个文件）
│   └── index/                          ← 保持不变（~26 个文件）
├── sentiment/
│   ├── bronze/{source}/YYYY/MM/DD.parquet  ← 保持不变（Paimon 日期分区，合理）
│   ├── silver/YYYY/MM/DD.parquet           ← 保持不变
│   └── gold/YYYY/MM/DD.parquet             ← 保持不变
├── events/                             ← 保持不变
├── models/                             ← 保持不变（ISO timestamp 版本控制）
└── .db/                                ← 保持不变
```

### `_manifest.json` 规格

```json
{
  "dataset": "kline",
  "layout": "per_symbol",
  "schema_version": 2,
  "columns": ["symbol","date","open","high","low","close","volume","amount","turnover_rate","prev_close","vwap"],
  "primary_key": ["symbol", "date"],
  "last_compaction": "2026-03-21T07:00:00Z",
  "entries": {
    "000001_SZ": {
      "rows": 1504,
      "date_min": "2020-01-02",
      "date_max": "2026-03-20",
      "bytes": 79431,
      "updated_at": "2026-03-21T07:00:00Z"
    }
  }
}
```

---

## 影响评估

| 指标 | 改前 | 改后 |
|------|------|------|
| kline 文件数 | 370,723 | ~4,900 + 1 manifest |
| 总文件数 | 381,550 | ~16,050 |
| kline 磁盘占用 | 2.9 GB | ~0.4 GB（↓87%，消除 parquet 小文件 overhead） |
| 读取一个 symbol 历史 | 75 次文件 I/O | 1 次文件 I/O |
| 写入（日增量更新） | 不变（read 1 + write 1） | 不变（read 1 + write 1） |
| DuckDB glob 消费方 | `kline/**/*.parquet` 自动兼容 | ✅ 无需改动 |

---

## 进度跟踪（2026-03-21）

### 已完成

- Python 侧已经切到 `market/kline/{symbol}.parquet` 单文件布局，并在写入时原子更新 `_manifest.json`。
- `DataGateway`、`data_inspector` 和所有仍在直接拼 `kline/**/*.parquet` 的主要 Python 消费方，已经改成 **flat 优先 / legacy 月分区 fallback**。
- C++ 引擎侧已增加 `kline_flat()`，CLI/train pipeline 都会先读 flat 文件，再回退到旧月目录。
- 一次性迁移脚本 `scripts/migrate_kline_consolidate.py` 已落地，支持 `--dry-run`、`--parallel`、`--symbols`、`--limit`、`--archive-monthly`。
- 新增回归测试 `tests/test_kline_storage_redesign.py`，覆盖 flat 写入、legacy 合并、manifest-first stats、gateway flat 优先读取。

### 样本验证结果

- 在真实数据抽样（`603083.SH`、`600150.SH`）复制到临时 data root 后：
  - dry-run：`2 symbols / 150 source files / 2,993 rows / 0 failures`
  - real run：输出 `2` 个 flat parquet、`1` 个 `_manifest.json`、并把 `75` 个旧月目录归档到 sibling archive
  - manifest 验证：`603083_SH.rows=1504`，`600150_SH.rows=1489`，总行数 `2993`
  - `DataGateway('/tmp/trade_kline_sample')._load_kline_local('603083.SH')` 直接读到 `1504` 行 flat 数据

### 实现备注

- 与原始计划相比，旧月份目录的 archive 位置改成 **data 根目录外侧的 sibling archive**，而不是 `market/kline/_archive/`。原因是很多消费者仍会对活跃 data root 做 `**/*.parquet` glob；如果把旧文件归档在活跃目录内，会造成重复读取。
- 真实全量 `data/market/kline` 迁移尚未在本次回复内完整跑完，因为对 38 万小文件做真实 dry-run 本身就需要较长时间；样本迁移和代码路径已经验证通过。

## TODO List

### Phase 1 — Python 层

- [x] **P1-1** `trade_py/data/market/kline/akshare.py`
  - `save_parquet()` 去掉月份 groupby，改为 `market/kline/{symbol}.parquet` 单文件写入
  - 合并语义不变（concat → dedup by date keep=last → sort → atomic rename）
  - 新增 `_update_manifest(symbol, df, path)` 私有方法：原子更新 `_manifest.json`

- [x] **P1-2** `trade_py/data/access/gateway.py`
  - `_load_kline_local()` 替换 75-月循环为单文件读取

- [x] **P1-3** `trade_py/data/paths.py`
  - 新增 `KLINE_MANIFEST = lambda root: market_dir(root, "kline") / "_manifest.json"`

- [x] **P1-4** `trade_py/utils/data_inspector.py`
  - `kline_coverage_stats()` 改为优先读 `_manifest.json`（O(1)），替代当前 DuckDB 全扫描
  - `kline_stats()` 同样受益：symbol 数 + 总行数从 manifest 直接读取

### Phase 2 — C++ 引擎层

- [x] **P2-1** `engine/include/trade/storage/storage_path.h`
  - 新增声明 `std::string kline_flat(const Symbol& symbol) const;`

- [x] **P2-2** `engine/src/storage/storage_path.cpp`
  - 实现 `kline_flat()` → `market/kline/{safe_symbol}.parquet`（保留 legacy `root/kline` fallback）

- [x] **P2-3** `engine/src/cli/shared.cpp`
  - DuckStore fast path 之后，年月 fallback 循环之前，先尝试 `kline_flat(symbol)`
  - 找到则直接使用，不进入月份循环（向后兼容：迁移期旧月份目录仍可用）

- [x] **P2-4** `engine/src/app/pipelines/train_pipeline.cpp`
  - 同样更新 kline 读取逻辑，优先 `kline_flat()`

### Phase 3 — 迁移脚本（一次性，用后可删）

- [x] **P3-1** `scripts/migrate_kline_consolidate.py`
  - 遍历所有 symbol（从 SQLite instruments 表或 glob 月份目录）
  - 对每个 symbol：读所有月份文件 → concat → dedup by date → sort → 写 flat 文件
  - 支持 `--dry-run`、`--parallel N`
  - 完成后输出：symbol 数、总行数、校验通过/失败数
  - 写入 `_manifest.json`

### Phase 4 — 验证 & 清理

- [x] **P4-1** 抽样验证迁移链路（样本 data root 下验证 603083.SH / 600150.SH 的 rows + date_min/date_max）
- [ ] **P4-2** 运行完整增量更新（`trade event run kline_update`），确认 flat 写入 + manifest 更新正常
- [x] **P4-3** 归档能力已实现并在样本 data root 验证：旧月份目录移动到 data 根目录外侧的 sibling archive，避免 `**/*.parquet` 重复读取
- [ ] **P4-4** 2 周后无问题，删除 archive

---

## 关键文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `trade_py/data/market/kline/akshare.py` | 修改 | 核心写入路径 + manifest 更新 |
| `trade_py/data/access/gateway.py` | 修改 | 核心读取路径 |
| `trade_py/data/paths.py` | 修改（小） | 新增 manifest 路径常量 |
| `trade_py/utils/data_inspector.py` | 修改 | manifest-first 查询 |
| `engine/include/trade/storage/storage_path.h` | 修改 | 新增 kline_flat() 声明 |
| `engine/src/storage/storage_path.cpp` | 修改 | 新增 kline_flat() 实现 |
| `engine/src/cli/shared.cpp` | 修改 | 优先 flat 路径 |
| `engine/src/app/pipelines/train_pipeline.cpp` | 修改 | 优先 flat 路径 |
| `scripts/migrate_kline_consolidate.py` | 新增（临时） | 一次性迁移脚本 |
| `trade_py/analysis/feature_builder.py` | 修改 | flat-first kline glob 解析 |
| `trade_py/analysis/label_builder.py` | 修改 | flat-first kline glob 解析 |
| `trade_py/analysis/factor_quantile.py` | 修改 | flat-first kline glob 解析 |
| `trade_py/analysis/sentiment_ic.py` | 修改 | flat-first kline glob 解析 |
| `trade_py/event/pipeline.py` | 修改 | flat-first kline glob 解析 |
| `trade_py/factors/technical.py` | 修改 | flat-first kline glob 解析 |
| `trade_py/intelligence/graph/learned.py` | 修改 | flat-first kline glob 解析 |

---

## 验证方法

```bash
# 迁移前记录基线
sqlite3 data/.db/trade.db "SELECT symbol, last_date FROM sync_state WHERE dataset='kline' ORDER BY symbol LIMIT 20;"

# 运行迁移
python scripts/migrate_kline_consolidate.py --dry-run
python scripts/migrate_kline_consolidate.py --parallel 4

# 验证文件数（应约 4,900）
find data/market/kline -maxdepth 1 -name "*.parquet" | wc -l

# 验证 manifest
python -c "import json; m=json.load(open('data/market/kline/_manifest.json')); print(len(m['entries']), 'symbols')"

# 验证 DuckDB glob 仍正常
python -c "
import duckdb
n = duckdb.query(\"SELECT count(*) FROM read_parquet('data/market/kline/**/*.parquet', union_by_name=true)\").fetchone()[0]
print('total rows:', n)
"
```
