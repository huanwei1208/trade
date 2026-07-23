from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from trade_py.data.market.kline.reconciliation import (
    KLINE_RECONCILIATION_SCHEMA_VERSION,
    current_reconciliation_path,
    reconcile_kline,
)


class FakeShadowProvider:
    name = "fake_shadow"

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def fetch(self, symbol: str, start: str, end: str, adjust: str = "none") -> pd.DataFrame:
        return self.frames.get(symbol, pd.DataFrame()).copy()


def _write_local_kline(root: Path, symbol: str, closes: list[float]) -> None:
    kline_root = root / "market" / "kline"
    kline_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, close in enumerate(closes, start=19):
        rows.append(
            {
                "symbol": symbol,
                "date": f"2026-03-{idx:02d}",
                "open": close,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": 1000,
                "amount": close * 100000,
                "turnover_rate": 1.0,
                "prev_close": close - 0.1,
                "vwap": close,
            }
        )
    pd.DataFrame(rows).to_parquet(kline_root / f"{symbol.replace('.', '_')}.parquet", index=False)
    (kline_root / "_manifest.json").write_text(
        json.dumps({"entries": {symbol.replace(".", "_"): {"rows": len(rows), "date_min": rows[0]["date"], "date_max": rows[-1]["date"]}}}),
        encoding="utf-8",
    )


def test_reconcile_kline_writes_passing_current_artifact(tmp_path: Path) -> None:
    symbol = "000001.SZ"
    _write_local_kline(tmp_path, symbol, [10.0, 10.2])
    provider = FakeShadowProvider({
        symbol: pd.DataFrame(
            [
                {"symbol": symbol, "date": "2026-03-19", "close": 10.0},
                {"symbol": symbol, "date": "2026-03-20", "close": 10.19},
            ]
        )
    })

    payload = reconcile_kline(
        tmp_path,
        symbols=[symbol],
        start="2026-03-19",
        end="2026-03-20",
        provider=provider,
        shadow_provider="fake_shadow",
    )

    current = current_reconciliation_path(tmp_path)
    stored = json.loads(current.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["schema_version"] == KLINE_RECONCILIATION_SCHEMA_VERSION
    assert payload["metrics"]["checked_rows"] == 2
    assert payload["metrics"]["block_rows"] == 0
    assert stored["run_id"] == payload["run_id"]
    assert stored["providers"]["shadow"] == ["fake_shadow"]


def test_reconcile_kline_dry_run_does_not_write_artifact(tmp_path: Path) -> None:
    symbol = "000001.SZ"
    _write_local_kline(tmp_path, symbol, [10.0])
    provider = FakeShadowProvider({symbol: pd.DataFrame([{"symbol": symbol, "date": "2026-03-19", "close": 10.0}])})

    payload = reconcile_kline(
        tmp_path,
        symbols=[symbol],
        start="2026-03-19",
        end="2026-03-19",
        provider=provider,
        shadow_provider="fake_shadow",
        dry_run=True,
    )

    assert payload["status"] == "pass"
    assert payload["dry_run"] is True
    assert not current_reconciliation_path(tmp_path).exists()


def test_reconcile_kline_blocks_large_close_basis(tmp_path: Path) -> None:
    symbol = "000001.SZ"
    _write_local_kline(tmp_path, symbol, [10.0])
    provider = FakeShadowProvider({symbol: pd.DataFrame([{"symbol": symbol, "date": "2026-03-19", "close": 8.0}])})

    payload = reconcile_kline(
        tmp_path,
        symbols=[symbol],
        start="2026-03-19",
        end="2026-03-19",
        provider=provider,
        shadow_provider="fake_shadow",
        block_basis_pct=2.0,
    )

    assert payload["status"] == "fail"
    assert payload["metrics"]["block_rows"] == 1
    assert payload["sample"][0]["reason_code"] == "CLOSE_BASIS_BLOCK"
