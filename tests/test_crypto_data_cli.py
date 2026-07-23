from __future__ import annotations

import json
import hashlib
from pathlib import Path
from threading import Barrier, Thread
from typing import Any

import pandas as pd
import pytest

from trade_py.cli import data as data_cli
from trade_py.data.market.cross_asset.assurance import BtcAssuranceConfig
from trade_py.data.market.cross_asset.btc import (
    BTC_PROVIDER_COLUMNS,
    COINGECKO_BTC_SHADOW_CONTRACT,
    OKX_BTC_CONTRACT,
    BtcProviderCapture,
    BtcProviderContract,
)
from trade_py.data.market.cross_asset.service import BtcMarketDataService
from trade_py.data.market.cross_asset.store import file_sha256
from trade_py.data.warehouse.crypto import (
    _apply_signal_lifecycle,
    _commit_crypto_validation_outputs,
    build_crypto_validation_outputs,
    persist_crypto_validation_outputs,
    read_crypto_validation_outputs,
    validate_crypto_btc_profile,
)


_AS_OF = pd.Timestamp("2026-01-10T12:00:00Z")


def _provider_frame(
    contract: BtcProviderContract,
    closes: list[float],
    *,
    run_id: str,
) -> pd.DataFrame:
    dates = pd.date_range(
        end=_AS_OF.normalize() - pd.Timedelta(days=1),
        periods=len(closes),
        freq="D",
        tz="UTC",
    )
    records: list[dict[str, Any]] = []
    for index, (date, close) in enumerate(zip(dates, closes)):
        is_primary = contract.role == "primary"
        records.append(
            {
                "provider": contract.provider,
                "venue": contract.venue,
                "instrument": contract.instrument,
                "base_asset": contract.base_asset,
                "quote_asset": contract.quote_asset,
                "interval": contract.interval,
                "bar_open_at": date,
                "bar_close_at": date + pd.Timedelta(days=1),
                "open": close if is_primary else float("nan"),
                "high": close * 1.01 if is_primary else float("nan"),
                "low": close * 0.99 if is_primary else float("nan"),
                "close": close,
                "volume": 1000.0 + index,
                "is_final": True,
                "fetched_at": _AS_OF,
                "available_at": date + pd.Timedelta(days=1),
                "payload_hash": hashlib.sha256(
                    f"{contract.provider}-{index}".encode()
                ).hexdigest(),
                "schema_version": contract.schema_version,
                "run_id": run_id,
                "source_timestamp_ms": int(date.timestamp() * 1000),
                "provider_status": "1" if is_primary else "complete",
            }
        )
    return pd.DataFrame.from_records(records, columns=BTC_PROVIDER_COLUMNS)


class _FrozenProvider:
    def __init__(
        self,
        contract: BtcProviderContract,
        frame: pd.DataFrame,
        raw_payload: bytes,
    ) -> None:
        self.contract = contract
        self._frame = frame
        self._raw_payload = raw_payload
        self.calls: list[dict[str, Any]] = []

    def capture(
        self,
        *,
        days: int,
        fetched_at: Any,
        run_id: str,
    ) -> BtcProviderCapture:
        capture_time = pd.Timestamp(fetched_at)
        frame = self._frame.copy()
        frame["fetched_at"] = capture_time
        frame["run_id"] = run_id
        self.calls.append(
            {"days": days, "fetched_at": capture_time, "run_id": run_id}
        )
        return BtcProviderCapture(
            contract=self.contract,
            frame=frame,
            raw_payloads=(self._raw_payload,),
            request_params=({"fixture": True},),
            fetched_at=capture_time,
            run_id=run_id,
        )


class _RollingFrozenProvider:
    def __init__(self, contract: BtcProviderContract) -> None:
        self.contract = contract

    def capture(
        self,
        *,
        days: int,
        fetched_at: Any,
        run_id: str,
    ) -> BtcProviderCapture:
        capture_time = pd.Timestamp(fetched_at)
        end = capture_time.normalize() - pd.Timedelta(days=1)
        dates = pd.date_range(end=end, periods=days, freq="D", tz="UTC")
        closes = [100.0 + float(date.toordinal() % 17) for date in dates]
        frame = _provider_frame(self.contract, closes, run_id=run_id)
        frame["bar_open_at"] = dates
        frame["bar_close_at"] = dates + pd.Timedelta(days=1)
        frame["available_at"] = frame["bar_close_at"]
        frame["fetched_at"] = capture_time
        frame["source_timestamp_ms"] = [int(date.timestamp() * 1000) for date in dates]
        frame["payload_hash"] = [
            hashlib.sha256(
                f"{self.contract.provider}:{date.isoformat()}:{close}".encode()
            ).hexdigest()
            for date, close in zip(dates, closes)
        ]
        raw = json.dumps(
            {"provider": self.contract.provider, "as_of": capture_time.isoformat()},
            sort_keys=True,
        ).encode()
        return BtcProviderCapture(
            contract=self.contract,
            frame=frame,
            raw_payloads=(raw,),
            request_params=({"fixture": "rolling"},),
            fetched_at=capture_time,
            run_id=run_id,
        )


class _FailingProvider:
    def __init__(self, contract: BtcProviderContract) -> None:
        self.contract = contract

    def capture(self, **_kwargs) -> BtcProviderCapture:
        raise RuntimeError(f"{self.contract.provider} unavailable")


def _ready_service(data_root: Path) -> BtcMarketDataService:
    closes = [100.0, 101.0, 102.0]
    primary = _FrozenProvider(
        OKX_BTC_CONTRACT,
        _provider_frame(OKX_BTC_CONTRACT, closes, run_id="fixture-okx"),
        b'{"provider":"okx","fixture":true}',
    )
    shadow = _FrozenProvider(
        COINGECKO_BTC_SHADOW_CONTRACT,
        _provider_frame(
            COINGECKO_BTC_SHADOW_CONTRACT,
            closes,
            run_id="fixture-binance",
        ),
        b'{"provider":"binance","fixture":true}',
    )
    config = BtcAssuranceConfig(
        minimum_history_days=3,
        recent_window_days=3,
        recent_coverage_required=1.0,
        full_coverage_required=1.0,
        shadow_days=3,
        shadow_required_days=3,
        acquisition_window_days=1,
        minimum_successful_acquisition_days=1,
        minimum_revision_overlap_days=0,
    )
    return BtcMarketDataService(
        data_root,
        primary_provider=primary,
        shadow_provider=shadow,
        config=config,
        days=3,
        max_attempts=1,
        retry_base_seconds=0.0,
        sleep=lambda _seconds: None,
        now=lambda: _AS_OF,
    )


def test_service_dry_run_with_frozen_captures_writes_nothing(tmp_path: Path) -> None:
    service = _ready_service(tmp_path)

    result = service.sync(dry_run=True, as_of=_AS_OF)

    assert result["data_readiness"] == "ready"
    assert result["publishable"] is True
    assert result["dry_run"] is True
    assert result["staged"] is None
    assert result["published"] is False
    assert result["acquisition"]["succeeded"] == 2
    assert not any(tmp_path.iterdir())


def test_consecutive_failed_acquisition_days_have_distinct_immutable_run_ids(
    tmp_path: Path,
) -> None:
    service = BtcMarketDataService(
        tmp_path,
        primary_provider=_FailingProvider(OKX_BTC_CONTRACT),
        shadow_provider=_FailingProvider(COINGECKO_BTC_SHADOW_CONTRACT),
        config=BtcAssuranceConfig(
            minimum_history_days=3,
            recent_window_days=3,
            shadow_days=3,
            shadow_required_days=3,
            acquisition_window_days=3,
            minimum_successful_acquisition_days=3,
        ),
        days=3,
        max_attempts=1,
        sleep=lambda _seconds: None,
    )

    first = service.sync(as_of=pd.Timestamp("2026-01-10T12:00:00Z"))
    second = service.sync(as_of=pd.Timestamp("2026-01-11T12:00:00Z"))

    assert first["published"] is False
    assert second["published"] is False
    assert first["run_id"] != second["run_id"]
    manifests = sorted(service.store.runs_root.glob("*/manifest.json"))
    assert len(manifests) == 2
    assert {
        json.loads(path.read_text(encoding="utf-8"))["acquisition_evidence"]["as_of"]
        for path in manifests
    } == {
        "2026-01-10T12:00:00+00:00",
        "2026-01-11T12:00:00+00:00",
    }


def test_ready_sync_atomically_publishes_canonical_pointer_raw_and_manifest(
    tmp_path: Path,
) -> None:
    service = _ready_service(tmp_path)

    result = service.sync(as_of=_AS_OF)

    assert result["data_readiness"] == "ready"
    assert result["published"] is True
    current = service.store.current()
    assert current is not None
    assert current["run_id"] == result["run_id"]
    assert service.store.compatibility_path.exists()
    assert service.store.current_path.exists()
    assert current["canonical_sha256"] == file_sha256(service.store.compatibility_path)

    run_dir = service.store.run_dir(result["run_id"])
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["provider_contracts"]["primary"]["instrument"] == "BTC-USDT"
    assert manifest["provider_contracts"]["shadow"]["quote_asset"] == "USDT"
    assert manifest["health"]["data_readiness"] == "ready"
    assert manifest["health"]["accuracy"]["status"] == "pass"
    assert manifest["health"]["source_stability"]["status"] == "pass"
    assert manifest["health"]["cross_source_validation"]["status"] == "pass"
    assert result["health"]["observed"]["watermark"] == "2026-01-09"
    assert manifest["retention_policy"] == {
        "minimum_completed_runs": 10,
        "strategy": "retain_all_no_automatic_pruning",
    }
    expected_artifacts = {
        "primary",
        "shadow",
        "canonical",
        "reconciliation",
        "revisions",
        "raw/okx/0000",
        "raw/binance/0000",
    }
    assert expected_artifacts <= set(manifest["artifact_hashes"])
    for provider in ("okx", "binance"):
        raw_path = run_dir / "raw" / provider / "0000.json"
        assert raw_path.exists()
        assert (
            manifest["artifact_hashes"][f"raw/{provider}/0000"]
            == file_sha256(raw_path)
        )

    canonical = pd.read_parquet(service.store.compatibility_path)
    assert canonical["provider"].eq("okx").all()
    assert canonical["instrument"].eq("BTC-USDT").all()
    assert canonical["quote_asset"].eq("USDT").all()
    assert canonical["date"].tolist() == list(
        pd.date_range("2026-01-07", periods=3, freq="D")
    )
    assert not list(service.store.crypto_root.glob(".*.tmp"))


def test_current_replay_uses_verified_predecessor_for_revision_quarantine(
    tmp_path: Path,
) -> None:
    service = _ready_service(tmp_path)
    service.config = BtcAssuranceConfig(
        minimum_history_days=2,
        recent_window_days=3,
        recent_coverage_required=0.66,
        full_coverage_required=0.66,
        shadow_days=3,
        shadow_required_days=3,
        acquisition_window_days=1,
        minimum_successful_acquisition_days=1,
        minimum_revision_overlap_days=0,
    )
    canonical_root = service.store.crypto_root
    canonical_root.mkdir(parents=True)
    predecessor = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-07", periods=3, freq="D"),
            "close": [100.0, 100.5, 102.0],
        }
    )
    predecessor.to_parquet(service.store.compatibility_path, index=False)

    synced = service.sync(as_of=_AS_OF)
    replay = service.validate_current()

    assert synced["data_readiness"] == "ready"
    assert synced["published"] is True
    assert synced["manifest"]["gates"][4]["metrics"]["warn_rows"] == 1
    assert replay["data_readiness"] == "ready"
    assert replay["integrity_errors"] == []
    assert replay["replay_errors"] == []


def test_validate_and_status_downgrade_an_aged_current_run(tmp_path: Path) -> None:
    service = _ready_service(tmp_path)
    assert service.sync(as_of=_AS_OF)["data_readiness"] == "ready"
    service.now = lambda: pd.Timestamp("2026-02-10T12:00:00Z")

    validated = service.validate_current()
    status = service.status()

    assert validated["data_readiness"] == "degraded"
    assert validated["reason_code"] == "CANONICAL_STALE"
    assert validated["operational_freshness"]["fresh"] is False
    assert validated["health"]["blocking_gate"] == "freshness"
    assert validated["health"]["blocking_reason_code"] == "CANONICAL_STALE"
    assert validated["health"]["freshness"]["status"] == "fail"
    assert validated["health"]["freshness"]["staleness_days"] == 31
    assert status["data_readiness"] == "degraded"
    assert status["reason_code"] == "CANONICAL_STALE"
    assert status["health"]["reason_codes"] == ["CANONICAL_STALE"]
    assert status["live_pilot"]["status"] == "pending"
    assert {
        item["name"]: item["status"]
        for item in status["live_pilot"]["items"]
    }["ads_current_pointer"] == "pending"


def test_corrupt_current_pointer_is_invalid_not_legacy_insufficient(tmp_path: Path) -> None:
    service = _ready_service(tmp_path)
    assert service.sync(as_of=_AS_OF)["published"] is True
    service.store.current_path.write_text("{broken", encoding="utf-8")

    validated = service.validate_current()
    status = service.status()

    assert validated["data_readiness"] == "invalid"
    assert validated["reason_code"] == "CURRENT_POINTER_INVALID"
    assert status["data_readiness"] == "invalid"
    assert status["reason_code"] == "CURRENT_POINTER_INVALID"


def test_daily_acquisition_and_staged_revision_bootstrap_publish_validate_rollback(
    tmp_path: Path,
) -> None:
    clock = [pd.Timestamp("2026-01-10T12:00:00Z")]
    config = BtcAssuranceConfig(
        minimum_history_days=3,
        recent_window_days=3,
        recent_coverage_required=1.0,
        full_coverage_required=1.0,
        shadow_days=3,
        shadow_required_days=3,
        acquisition_window_days=3,
        minimum_successful_acquisition_days=3,
        minimum_revision_overlap_days=2,
    )
    service = BtcMarketDataService(
        tmp_path,
        primary_provider=_RollingFrozenProvider(OKX_BTC_CONTRACT),
        shadow_provider=_RollingFrozenProvider(COINGECKO_BTC_SHADOW_CONTRACT),
        config=config,
        days=3,
        max_attempts=1,
        sleep=lambda _seconds: None,
        now=lambda: clock[0],
    )

    first = service.sync(as_of=clock[0])
    clock[0] += pd.Timedelta(days=1)
    second = service.sync(as_of=clock[0])
    clock[0] += pd.Timedelta(days=1)
    third = service.sync(as_of=clock[0])
    third_run_id = third["run_id"]
    clock[0] += pd.Timedelta(days=1)
    fourth = service.sync(as_of=clock[0])

    assert first["data_readiness"] == "degraded"
    assert second["data_readiness"] == "degraded"
    assert third["data_readiness"] == "ready" and third["published"] is True
    assert fourth["data_readiness"] == "ready" and fourth["published"] is True
    validated = service.validate_current()
    assert validated["data_readiness"] == "ready"
    assert validated["integrity_errors"] == []

    rollback = service.store.rollback(third_run_id)
    assert rollback["run_id"] == third_run_id
    assert service.store.current()["run_id"] == third_run_id
    assert Path(rollback["rollback_audit_path"]).is_file()


def test_status_live_pilot_reports_local_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [pd.Timestamp("2026-01-10T12:00:00Z")]
    config = BtcAssuranceConfig(
        minimum_history_days=3,
        recent_window_days=3,
        recent_coverage_required=1.0,
        full_coverage_required=1.0,
        shadow_days=3,
        shadow_required_days=3,
        acquisition_window_days=3,
        minimum_successful_acquisition_days=3,
        minimum_revision_overlap_days=2,
    )
    service = BtcMarketDataService(
        tmp_path,
        primary_provider=_RollingFrozenProvider(OKX_BTC_CONTRACT),
        shadow_provider=_RollingFrozenProvider(COINGECKO_BTC_SHADOW_CONTRACT),
        config=config,
        days=3,
        max_attempts=1,
        sleep=lambda _seconds: None,
        now=lambda: clock[0],
    )
    monkeypatch.setenv("COINGECKO_API_KEY", "fixture-key")

    first = service.sync(as_of=clock[0])
    clock[0] += pd.Timedelta(days=1)
    service.sync(as_of=clock[0])
    clock[0] += pd.Timedelta(days=1)
    third = service.sync(as_of=clock[0])
    clock[0] += pd.Timedelta(days=1)
    service.sync(as_of=clock[0])
    service.store.rollback(third["run_id"])
    ads_pointer = tmp_path / "warehouse" / "ads" / "_crypto_validation_current.json"
    ads_pointer.parent.mkdir(parents=True)
    ads_pointer.write_text(
        json.dumps({"run_id": "validation", "generation_id": "generation"}),
        encoding="utf-8",
    )

    status = service.status()
    pilot = {item["name"]: item for item in status["live_pilot"]["items"]}

    assert status["live_pilot"]["status"] == "pass"
    assert pilot["free_api_mode"]["status"] == "pass"
    assert pilot["provider_contracts"]["status"] == "pass"
    assert pilot["published_current"]["status"] == "pass"
    assert pilot["ads_current_pointer"]["status"] == "pass"
    assert pilot["qualified_acquisition_days"]["evidence"]["qualified_days"] == 3
    assert pilot["qualified_acquisition_days"]["status"] == "pass"
    assert pilot["revision_overlap"]["status"] == "pass"
    assert pilot["first_pointer_switch"]["status"] == "pass"
    assert pilot["rollback_rehearsal"]["status"] == "pass"


class _CliService:
    calls: list[tuple[Any, ...]] = []
    sync_payload: dict[str, Any] = {
        "mode": "sync",
        "data_readiness": "ready",
        "run_id": "cli-ready",
        "published": True,
        "acquisition": {"failed": 0},
        "gates": [],
    }

    def __init__(self, data_root: str | Path, **_kwargs: Any) -> None:
        self.data_root = str(data_root)

    def sync(self, *, dry_run: bool = False) -> dict[str, Any]:
        self.calls.append(("sync", self.data_root, dry_run))
        return {**self.sync_payload, "dry_run": dry_run}

    def validate_current(self) -> dict[str, Any]:
        self.calls.append(("validate", self.data_root))
        return {
            "mode": "validate",
            "data_readiness": "ready",
            "run_id": "cli-ready",
            "validated": True,
            "gates": [],
        }

    def status(self) -> dict[str, Any]:
        self.calls.append(("status", self.data_root))
        return {
            "mode": "status",
            "data_readiness": "ready",
            "run_id": "cli-ready",
            "gates": [],
        }


def test_cross_asset_btc_legacy_alias_modes_and_json(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from trade_py.data.market.crypto import service as service_module

    _CliService.calls = []
    _CliService.sync_payload = {
        "mode": "sync",
        "data_readiness": "ready",
        "run_id": "cli-ready",
        "published": True,
        "acquisition": {"failed": 0},
        "gates": [],
    }
    monkeypatch.setattr(service_module, "BtcMarketDataService", _CliService)
    root = str(tmp_path)

    commands = [
        (["cross-asset", "btc", "--data-root", root, "--json"], "sync"),
        (
            [
                "cross-asset",
                "btc",
                "--data-root",
                root,
                "--mode",
                "sync",
                "--json",
            ],
            "sync",
        ),
        (
            [
                "cross-asset",
                "btc",
                "--data-root",
                root,
                "--mode",
                "validate",
                "--dry-run",
                "--json",
            ],
            "validate",
        ),
        (
            [
                "cross-asset",
                "btc",
                "--data-root",
                root,
                "--mode",
                "status",
                "--json",
            ],
            "status",
        ),
    ]
    payloads: list[dict[str, Any]] = []
    for argv, expected_mode in commands:
        assert data_cli.main(argv) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["mode"] == expected_mode
        payloads.append(payload)

    assert payloads[0] == payloads[1]
    assert payloads[2]["dry_run"] is True
    assert _CliService.calls == [
        ("sync", root, False),
        ("sync", root, False),
        ("validate", root),
        ("status", root),
    ]


def test_cross_asset_btc_strict_degraded_and_d3_block_exit_codes(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from trade_py.data.market.crypto import service as service_module

    monkeypatch.setattr(service_module, "BtcMarketDataService", _CliService)
    root = str(tmp_path)
    base = [
        "cross-asset",
        "btc",
        "--data-root",
        root,
        "--strict",
        "--json",
    ]

    _CliService.sync_payload = {
        "mode": "sync",
        "data_readiness": "degraded",
        "run_id": "cli-degraded",
        "published": False,
        "acquisition": {"failed": 0},
        "gates": [{"gate": "D3", "status": "pass", "reason_code": "SOURCES_RECONCILED"}],
    }
    assert data_cli.main(base) == 3
    degraded = json.loads(capsys.readouterr().out)
    assert degraded["data_readiness"] == "degraded"

    _CliService.sync_payload = {
        "mode": "sync",
        "data_readiness": "degraded",
        "run_id": "cli-divergence",
        "published": False,
        "acquisition": {"failed": 0},
        "gates": [
            {
                "gate": "D3",
                "status": "fail",
                "reason_code": "SOURCE_DIVERGENCE",
                "metrics": {"block_rows": 1},
            }
        ],
    }
    assert data_cli.main(base) == 4
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["gates"][0]["metrics"]["block_rows"] == 1


def test_compatibility_fetch_and_scheduled_job_fail_on_unpublished_btc(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from trade_py.data.market.cross_asset import akshare as cross_asset_module
    from trade_py.data.market.cross_asset import service as service_module
    from trade_py.jobs import JOB_REGISTRY, _job_crypto_btc_fetch

    _CliService.sync_payload = {
        "mode": "sync",
        "data_readiness": "degraded",
        "run_id": "not-published",
        "published": False,
        "acquisition": {"failed": 1},
        "gates": [],
    }
    monkeypatch.setattr(service_module, "BtcMarketDataService", _CliService)
    with pytest.raises(RuntimeError, match="did not publish"):
        cross_asset_module.fetch_btc(str(tmp_path))

    with pytest.raises(RuntimeError, match="未发布"):
        _job_crypto_btc_fetch(str(tmp_path))

    from trade_py.jobs import JobQualityWarning

    _CliService.sync_payload = {
        "mode": "sync",
        "data_readiness": "degraded",
        "run_id": "pilot-pending",
        "published": False,
        "staged": {"run_id": "pilot-pending"},
        "gates": [
            {
                "gate": gate,
                "status": "fail" if gate == "D1" else "pass",
                "reason_code": (
                    "ACQUISITION_STABILITY_INSUFFICIENT" if gate == "D1" else "PASS"
                ),
                "metrics": (
                    {
                        "successful_acquisition_days": 2,
                        "required_successful_acquisition_days": 29,
                    }
                    if gate == "D1"
                    else {}
                ),
            }
            for gate in ("D0", "D1", "D2", "D3", "D4")
        ],
    }
    with pytest.raises(JobQualityWarning, match="qualified_days=2/29"):
        _job_crypto_btc_fetch(str(tmp_path))
    assert JOB_REGISTRY["crypto_btc_fetch"].schedule == ["daily 09:00"]


def test_unpublished_assurance_run_suppresses_active_evidence_with_lineage(
    tmp_path: Path,
) -> None:
    service = BtcMarketDataService(
        tmp_path,
        primary_provider=_FailingProvider(OKX_BTC_CONTRACT),
        shadow_provider=_FailingProvider(COINGECKO_BTC_SHADOW_CONTRACT),
        days=3,
        max_attempts=1,
        sleep=lambda _seconds: None,
    )
    failed = service.sync(as_of=_AS_OF)
    table = tmp_path / "warehouse" / "ads" / "ads_crypto_volatility_validation.parquet"
    table.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "previous-validated",
                "watermark": "2026-01-08",
                "active_signal_status": "validated",
                "consecutive_null_crossings": 0,
                "ci_crosses_null": False,
                "is_active": True,
            }
        ]
    ).to_parquet(table, index=False)

    result = validate_crypto_btc_profile(
        tmp_path,
        data_assurance_override=failed,
    )
    active = pd.read_parquet(table)
    active = active.loc[active["is_active"].fillna(False).astype(bool)].iloc[0]
    readiness = pd.read_parquet(
        tmp_path / "warehouse" / "ads" / "ads_crypto_data_readiness_report.parquet"
    ).iloc[-1]

    assert failed["published"] is False
    assert result["validation"]["lifecycle"]["suppressed_by_data_gate"] is True
    assert active["active_signal_status"] == "candidate"
    assert readiness["evidence_ref"] == str(
        service.store.run_dir(failed["run_id"]) / "manifest.json"
    )


def test_crypto_ads_outputs_persist_data_health_json() -> None:
    health = {
        "data_readiness": "degraded",
        "blocking_gate": "D3",
        "blocking_reason_code": "SOURCE_DIVERGENCE",
        "cross_source_validation": {"status": "fail", "block_rows": 1},
        "evidence_refs": {"manifest_path": "/tmp/btc/manifest.json"},
    }
    outputs = build_crypto_validation_outputs(
        data_assurance={
            "run_id": "data-diverged",
            "data_readiness": "degraded",
            "health": health,
            "gates": [
                {
                    "gate": "D3",
                    "status": "fail",
                    "reason_code": "SOURCE_DIVERGENCE",
                }
            ],
        },
        validation={
            "run_id": "validation-diverged",
            "status": "candidate",
            "data_readiness": "degraded",
            "reasons": ["DATA_READINESS_DEGRADED"],
            "lifecycle": {
                "active_signal_status": "candidate",
                "activate_run": True,
                "suppressed_by_data_gate": True,
            },
        },
        reconciliation=pd.DataFrame(),
    )

    readiness_health = json.loads(
        outputs["ads_crypto_data_readiness_report"].iloc[0]["data_health_json"]
    )
    validation_health = json.loads(
        outputs["ads_crypto_volatility_validation"].iloc[0]["data_health_json"]
    )
    audit_health = json.loads(
        outputs["ads_research_validation_run"].iloc[0]["data_health_json"]
    )

    assert readiness_health == health
    assert validation_health["blocking_gate"] == "D3"
    assert audit_health["cross_source_validation"]["block_rows"] == 1


def test_crypto_profile_dry_run_does_not_create_warehouse(tmp_path: Path) -> None:
    result = validate_crypto_btc_profile(tmp_path, dry_run=True)

    assert result["profile"] == "crypto-btc-v1"
    assert result["dry_run"] is True
    assert set(result["outputs"]) == {
        "ads_crypto_data_readiness_report",
        "ads_crypto_provider_reconciliation",
        "ads_crypto_volatility_validation",
        "ads_research_validation_run",
    }
    assert not (tmp_path / "warehouse").exists()


def test_latest_common_profile_excludes_primary_day_without_shadow_close(
    tmp_path: Path,
) -> None:
    service = _ready_service(tmp_path)
    service.config = BtcAssuranceConfig(
        minimum_history_days=3,
        recent_window_days=3,
        recent_coverage_required=1.0,
        full_coverage_required=1.0,
        shadow_days=3,
        shadow_required_days=2,
        acquisition_window_days=1,
        minimum_successful_acquisition_days=1,
        minimum_revision_overlap_days=0,
    )
    service.shadow_provider._frame = service.shadow_provider._frame.iloc[:-1].copy()
    synced = service.sync(as_of=_AS_OF)
    assert synced["data_readiness"] == "ready"

    result = validate_crypto_btc_profile(
        tmp_path,
        dry_run=True,
        now=lambda: _AS_OF,
    )

    assert result["effective_as_of"] == "2026-01-08"
    assert result["validation"]["watermark"] == "2026-01-08"


def test_profile_reads_canonical_and_reconciliation_from_one_immutable_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from trade_py.data.warehouse import crypto as crypto_warehouse

    service = _ready_service(tmp_path)
    synced = service.sync(as_of=_AS_OF)
    original_validate = service.validate_current

    def mutate_flat_after_validation(*, _lock: bool = True):
        result = original_validate(_lock=_lock)
        replacement = pd.read_parquet(service.store.compatibility_path)
        replacement.loc[:, "close"] = 999.0
        replacement.to_parquet(service.store.compatibility_path, index=False)
        return result

    monkeypatch.setattr(service, "validate_current", mutate_flat_after_validation)
    monkeypatch.setattr(
        crypto_warehouse,
        "BtcMarketDataService",
        lambda _data_root, **_kwargs: service,
    )

    result = validate_crypto_btc_profile(tmp_path, dry_run=True, now=lambda: _AS_OF)

    assert result["data_assurance"]["run_id"] == synced["run_id"]
    assert result["validation"]["watermark"] == "2026-01-09"
    assert result["validation"]["input_evidence"]["data_assurance"]["data_run_id"] == synced[
        "run_id"
    ]
    assert pd.read_parquet(service.store.compatibility_path)["close"].eq(999.0).all()


def test_ready_to_stale_same_input_creates_a_new_suppression_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from trade_py.data.warehouse import crypto as crypto_warehouse

    service = _ready_service(tmp_path)
    service.sync(as_of=_AS_OF)
    monkeypatch.setattr(
        crypto_warehouse,
        "BtcMarketDataService",
        lambda _data_root, **_kwargs: service,
    )
    ready = validate_crypto_btc_profile(tmp_path, dry_run=True, now=lambda: _AS_OF)
    validation_path = (
        tmp_path
        / "warehouse"
        / "ads"
        / "ads_crypto_volatility_validation.parquet"
    )
    validation_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": ready["validation"]["run_id"],
                "watermark": ready["validation"]["watermark"],
                "active_signal_status": "validated",
                "consecutive_null_crossings": 0,
                "ci_crosses_null": False,
                "pending_recheck": False,
                "is_active": True,
            }
        ]
    ).to_parquet(validation_path, index=False)
    service.now = lambda: pd.Timestamp("2026-02-10T12:00:00Z")

    stale = validate_crypto_btc_profile(tmp_path, dry_run=False)
    history = pd.read_parquet(validation_path)
    active = history.loc[history["is_active"].fillna(False).astype(bool)].iloc[0]

    assert stale["validation"]["run_id"] != ready["validation"]["run_id"]
    assert active["data_readiness"] == "degraded"
    assert active["active_signal_status"] == "candidate"
    assert bool(active["suppressed_by_data_gate"]) is True


def test_signal_lifecycle_requires_two_null_crossings_and_suppresses_bad_data(
    tmp_path: Path,
) -> None:
    table = tmp_path / "warehouse" / "ads" / "ads_crypto_volatility_validation.parquet"
    table.parent.mkdir(parents=True)
    pd.DataFrame([
        {
            "run_id": "validated-0",
            "active_signal_status": "validated",
            "consecutive_null_crossings": 0,
            "ci_crosses_null": False,
            "is_active": True,
        }
    ]).to_parquet(table, index=False)
    monitoring = {
        "run_id": "monitoring-1",
        "status": "monitoring",
        "data_readiness": "ready",
        "confidence_interval": {"lower": 0.9, "upper": 1.1},
    }

    first = _apply_signal_lifecycle(tmp_path, monitoring)
    first_lifecycle = first["lifecycle"]
    assert first_lifecycle["active_signal_status"] == "validated"
    assert first_lifecycle["pending_recheck"] is True
    assert first_lifecycle["consecutive_null_crossings"] == 1

    pd.DataFrame([
        {
            "run_id": "monitoring-1",
            **first_lifecycle,
            "is_active": True,
        }
    ]).to_parquet(table, index=False)
    second = _apply_signal_lifecycle(
        tmp_path,
        {**monitoring, "run_id": "monitoring-2"},
    )
    assert second["lifecycle"]["active_signal_status"] == "monitoring"
    assert second["lifecycle"]["consecutive_null_crossings"] == 2

    suppressed = _apply_signal_lifecycle(
        tmp_path,
        {
            "run_id": "degraded-1",
            "status": "validated",
            "data_readiness": "degraded",
            "confidence_interval": {"lower": 1.1, "upper": 1.5},
        },
    )
    assert suppressed["lifecycle"]["active_signal_status"] == "candidate"
    assert suppressed["lifecycle"]["suppressed_by_data_gate"] is True


def test_lifecycle_counts_null_crossings_only_on_qualified_monthly_rechecks(
    tmp_path: Path,
) -> None:
    table = tmp_path / "warehouse" / "ads" / "ads_crypto_volatility_validation.parquet"
    table.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "validated-0",
                "watermark": "2026-01-01",
                "active_signal_status": "validated",
                "consecutive_null_crossings": 0,
                "ci_crosses_null": False,
                "is_active": True,
            }
        ]
    ).to_parquet(table, index=False)
    base = {
        "status": "monitoring",
        "data_readiness": "ready",
        "confidence_interval": {"lower": 0.9, "upper": 1.1},
    }

    daily = _apply_signal_lifecycle(
        tmp_path,
        {**base, "run_id": "daily", "watermark": "2026-01-02"},
    )
    assert daily["lifecycle"]["activate_run"] is False
    assert daily["lifecycle"]["consecutive_null_crossings"] == 0

    first = _apply_signal_lifecycle(
        tmp_path,
        {**base, "run_id": "monthly-1", "watermark": "2026-01-29"},
    )
    assert first["lifecycle"]["consecutive_null_crossings"] == 1
    assert first["lifecycle"]["active_signal_status"] == "validated"
    pd.DataFrame(
        [
            {
                "run_id": "monthly-1",
                "watermark": "2026-01-29",
                **first["lifecycle"],
                "is_active": True,
            }
        ]
    ).to_parquet(table, index=False)

    second = _apply_signal_lifecycle(
        tmp_path,
        {**base, "run_id": "monthly-2", "watermark": "2026-02-26"},
    )
    assert second["lifecycle"]["consecutive_null_crossings"] == 2
    assert second["lifecycle"]["active_signal_status"] == "monitoring"


def test_monitoring_without_a_null_crossing_does_not_downgrade_validated(
    tmp_path: Path,
) -> None:
    table = tmp_path / "warehouse" / "ads" / "ads_crypto_volatility_validation.parquet"
    table.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "validated-0",
                "watermark": "2026-01-01",
                "active_signal_status": "validated",
                "consecutive_null_crossings": 0,
                "ci_crosses_null": False,
                "is_active": True,
            }
        ]
    ).to_parquet(table, index=False)

    result = _apply_signal_lifecycle(
        tmp_path,
        {
            "run_id": "monitoring-noncross",
            "watermark": "2026-02-01",
            "status": "monitoring",
            "data_readiness": "ready",
            "confidence_interval": {"lower": 1.01, "upper": 1.20},
        },
    )

    assert result["lifecycle"]["active_signal_status"] == "validated"
    assert result["lifecycle"]["consecutive_null_crossings"] == 0


def test_concurrent_lifecycle_commits_serialize_the_two_crossing_transition(
    tmp_path: Path,
) -> None:
    table = tmp_path / "warehouse" / "ads" / "ads_crypto_volatility_validation.parquet"
    table.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "validated-0",
                "active_signal_status": "validated",
                "consecutive_null_crossings": 0,
                "ci_crosses_null": False,
                "is_active": True,
            }
        ]
    ).to_parquet(table, index=False)
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def commit(index: int) -> None:
        try:
            barrier.wait()
            _commit_crypto_validation_outputs(
                tmp_path,
                data_assurance={
                    "run_id": f"data-{index}",
                    "data_readiness": "ready",
                    "gates": [],
                },
                validation={
                    "run_id": f"monitoring-{index}",
                    "status": "monitoring",
                    "data_readiness": "ready",
                    "confidence_interval": {"lower": 0.9, "upper": 1.1},
                    "reasons": [],
                },
                reconciliation=pd.DataFrame(),
                dry_run=False,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [Thread(target=commit, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    history = pd.read_parquet(table)
    active = history.loc[history["is_active"].fillna(False).astype(bool)]
    assert len(active) == 1
    assert active.iloc[0]["active_signal_status"] == "monitoring"
    assert int(active.iloc[0]["consecutive_null_crossings"]) == 2


def test_older_validation_cannot_supersede_a_newer_active_run(tmp_path: Path) -> None:
    table = tmp_path / "warehouse" / "ads" / "ads_crypto_volatility_validation.parquet"
    table.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "newer-active",
                "watermark": "2026-03-01",
                "active_signal_status": "validated",
                "consecutive_null_crossings": 0,
                "ci_crosses_null": False,
                "is_active": True,
            }
        ]
    ).to_parquet(table, index=False)

    enriched, _outputs, _paths = _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance={"run_id": "older-data", "data_readiness": "ready", "gates": []},
        validation={
            "run_id": "older-validation",
            "watermark": "2026-02-01",
            "status": "validated",
            "data_readiness": "ready",
            "reasons": [],
        },
        reconciliation=pd.DataFrame(),
        dry_run=False,
    )
    history = pd.read_parquet(table)
    active = history.loc[history["is_active"].fillna(False).astype(bool)]

    assert enriched["lifecycle"]["stale_write_rejected"] is True
    assert len(active) == 1
    assert active.iloc[0]["run_id"] == "newer-active"


def test_older_degraded_run_suppresses_newer_validated_evidence(tmp_path: Path) -> None:
    table = tmp_path / "warehouse" / "ads" / "ads_crypto_volatility_validation.parquet"
    table.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "run_id": "newer-active",
                "watermark": "2026-03-01",
                "active_signal_status": "validated",
                "consecutive_null_crossings": 0,
                "ci_crosses_null": False,
                "is_active": True,
            }
        ]
    ).to_parquet(table, index=False)

    enriched, _outputs, _paths = _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance={"run_id": "rollback-data", "data_readiness": "degraded", "gates": []},
        validation={
            "run_id": "rollback-suppression",
            "watermark": "2026-01-01",
            "status": "candidate",
            "data_readiness": "degraded",
            "reasons": ["DATA_READINESS_DEGRADED"],
        },
        reconciliation=pd.DataFrame(),
        dry_run=False,
    )
    history = pd.read_parquet(table)
    active = history.loc[history["is_active"].fillna(False).astype(bool)]

    assert enriched["lifecycle"]["stale_write_rejected"] is False
    assert enriched["lifecycle"]["suppressed_by_data_gate"] is True
    assert len(active) == 1
    assert active.iloc[0]["run_id"] == "rollback-suppression"
    assert active.iloc[0]["active_signal_status"] == "candidate"


def test_ads_reader_uses_current_pointer_during_a_partial_flat_table_update(
    tmp_path: Path,
) -> None:
    def commit(run_id: str) -> dict[str, pd.DataFrame]:
        _enriched, outputs, _paths = _commit_crypto_validation_outputs(
            tmp_path,
            data_assurance={
                "run_id": f"data-{run_id}",
                "data_readiness": "degraded",
                "gates": [],
            },
            validation={
                "run_id": run_id,
                "watermark": "2026-01-09",
                "status": "candidate",
                "data_readiness": "degraded",
                "reasons": ["DATA_READINESS_DEGRADED"],
            },
            reconciliation=pd.DataFrame(),
            dry_run=False,
        )
        return outputs

    commit("r1")
    new_outputs = build_crypto_validation_outputs(
        data_assurance={"run_id": "data-r2", "data_readiness": "degraded", "gates": []},
        validation={
            "run_id": "r2",
            "watermark": "2026-01-10",
            "status": "candidate",
            "data_readiness": "degraded",
            "reasons": ["DATA_READINESS_DEGRADED"],
            "lifecycle": {
                "active_signal_status": "candidate",
                "activate_run": True,
                "suppressed_by_data_gate": True,
            },
        },
        reconciliation=pd.DataFrame(),
    )
    readiness_path = (
        tmp_path / "warehouse" / "ads" / "ads_crypto_data_readiness_report.parquet"
    )
    partial = pd.concat(
        [pd.read_parquet(readiness_path), new_outputs["ads_crypto_data_readiness_report"]],
        ignore_index=True,
    )
    partial.to_parquet(readiness_path, index=False)

    snapshot = read_crypto_validation_outputs(tmp_path)

    assert snapshot["current"]["run_id"] == "r1"
    assert all(frame["run_id"].astype(str).eq("r1").all() for frame in snapshot["tables"].values())


def test_late_validation_cannot_activate_after_the_btc_current_run_changes(
    tmp_path: Path,
) -> None:
    service = _ready_service(tmp_path)
    first_sync = service.sync(as_of=_AS_OF)
    first_assurance = service.validate_current()
    second_sync = service.sync(as_of=_AS_OF)
    second_assurance = service.validate_current()
    assert first_sync["run_id"] != second_sync["run_id"]

    _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance=second_assurance,
        validation={
            "run_id": "validation-current",
            "watermark": "2026-01-09",
            "status": "validated",
            "data_readiness": "ready",
            "reasons": [],
        },
        reconciliation=pd.DataFrame(),
        dry_run=False,
        enforce_data_lineage=True,
    )
    late_ready, _outputs, _paths = _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance=first_assurance,
        validation={
            "run_id": "validation-late-ready",
            "watermark": "2026-01-09",
            "status": "validated",
            "data_readiness": "ready",
            "reasons": [],
        },
        reconciliation=pd.DataFrame(),
        dry_run=False,
        enforce_data_lineage=True,
    )
    late_degraded, _outputs, _paths = _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance={**first_assurance, "data_readiness": "degraded"},
        validation={
            "run_id": "validation-late-degraded",
            "watermark": "2026-01-09",
            "status": "candidate",
            "data_readiness": "degraded",
            "reasons": ["DATA_READINESS_DEGRADED"],
        },
        reconciliation=pd.DataFrame(),
        dry_run=False,
        enforce_data_lineage=True,
    )
    snapshot = read_crypto_validation_outputs(tmp_path)

    assert late_ready["lifecycle"]["activate_run"] is False
    assert late_ready["lifecycle"]["data_lineage_reason"] == "DATA_RUN_SUPERSEDED"
    assert late_degraded["lifecycle"]["activate_run"] is False
    assert snapshot["current"]["run_id"] == "validation-current"


def test_provider_rollback_reactivates_a_new_generation_of_the_same_validation_run(
    tmp_path: Path,
) -> None:
    service = _ready_service(tmp_path)
    first_sync = service.sync(as_of=_AS_OF)
    assurance_a = service.validate_current()
    validation_v = {
        "run_id": "validation-v",
        "watermark": "2026-01-09",
        "status": "rejected",
        "data_readiness": "ready",
        "reasons": ["SIGNIFICANT_OPPOSITE_EFFECT"],
    }
    _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance=assurance_a,
        validation=validation_v,
        reconciliation=pd.DataFrame(),
        dry_run=False,
        enforce_data_lineage=True,
    )
    pointer_path = tmp_path / "warehouse" / "ads" / "_crypto_validation_current.json"
    first_generation = json.loads(pointer_path.read_text(encoding="utf-8"))["generation_id"]

    second_sync = service.sync(as_of=_AS_OF)
    assurance_b = service.validate_current()
    _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance=assurance_b,
        validation={
            "run_id": "validation-w",
            "watermark": "2026-01-09",
            "status": "validated",
            "data_readiness": "ready",
            "reasons": [],
        },
        reconciliation=pd.DataFrame(),
        dry_run=False,
        enforce_data_lineage=True,
    )
    late, _outputs, _paths = _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance=assurance_a,
        validation=validation_v,
        reconciliation=pd.DataFrame(),
        dry_run=False,
        enforce_data_lineage=True,
    )
    assert late["lifecycle"]["activate_run"] is False

    service.store.rollback(first_sync["run_id"])
    restored_assurance = service.validate_current()
    replay, _outputs, _paths = _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance=restored_assurance,
        validation=validation_v,
        reconciliation=pd.DataFrame(),
        dry_run=False,
        enforce_data_lineage=True,
    )
    snapshot = read_crypto_validation_outputs(tmp_path)

    assert first_sync["run_id"] != second_sync["run_id"]
    assert replay["lifecycle"]["activate_run"] is True
    assert snapshot["current"]["run_id"] == "validation-v"
    assert snapshot["current"]["generation_id"] != first_generation
    assert snapshot["tables"]["ads_crypto_volatility_validation"].iloc[0][
        "active_signal_status"
    ] == "rejected"


def test_ads_transaction_restores_all_tables_when_one_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from trade_py.data.warehouse import crypto_store as crypto_warehouse

    validation = {
        "run_id": "atomic-run",
        "contract_version": "crypto-btc-volatility-v1",
        "hypothesis_id": "btc-volatility-persistence-h1",
        "status": "insufficient_data",
        "data_readiness": "ready",
        "causal": False,
        "recommendation": None,
        "watermark": "2026-01-09",
        "input_evidence": {"input_hash": "x"},
        "sample": {},
        "folds": [],
        "placebos": {},
        "reasons": ["MINIMUM_EVENT_COUNT_NOT_MET"],
        "lifecycle": {"active_signal_status": "candidate"},
    }
    outputs = build_crypto_validation_outputs(
        data_assurance={"run_id": "data-run", "data_readiness": "ready", "gates": []},
        validation=validation,
        reconciliation=pd.DataFrame(),
    )
    real_replace = crypto_warehouse.os.replace
    replacements = 0

    def fail_second_table(source, destination):
        nonlocal replacements
        if str(destination).endswith(".parquet"):
            replacements += 1
            if replacements == 2:
                raise OSError("injected ADS replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(crypto_warehouse.os, "replace", fail_second_table)
    with pytest.raises(OSError, match="injected ADS replace failure"):
        persist_crypto_validation_outputs(tmp_path, outputs, dry_run=False)

    ads_root = tmp_path / "warehouse" / "ads"
    assert not list(ads_root.glob("*.parquet"))
    assert not list((ads_root / "_validation_receipts").glob("*.json"))
    assert not list(ads_root.glob(".validation-*.tmp"))


def test_ads_keyboard_interrupt_after_receipt_restores_before_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from trade_py.data.warehouse import crypto_store as crypto_warehouse

    def commit(run_id: str, status: str, interval: dict[str, float] | None = None):
        return _commit_crypto_validation_outputs(
            tmp_path,
            data_assurance={"run_id": f"data-{run_id}", "data_readiness": "ready", "gates": []},
            validation={
                "run_id": run_id,
                "status": status,
                "data_readiness": "ready",
                "confidence_interval": interval,
                "reasons": [],
            },
            reconciliation=pd.DataFrame(),
            dry_run=False,
        )

    commit("r1", "validated", {"lower": 1.1, "upper": 1.4})
    real_promote = crypto_warehouse._promote_validation_pointer

    def interrupt_after_receipt(_ads_root, payload):
        if payload.get("run_id") == "r2":
            raise KeyboardInterrupt("injected stop after receipt")
        return real_promote(_ads_root, payload)

    monkeypatch.setattr(crypto_warehouse, "_promote_validation_pointer", interrupt_after_receipt)
    with pytest.raises(KeyboardInterrupt, match="injected stop"):
        commit("r2", "monitoring", {"lower": 0.9, "upper": 1.1})

    ads_root = tmp_path / "warehouse" / "ads"
    pointer = json.loads((ads_root / "_crypto_validation_current.json").read_text(encoding="utf-8"))
    assert pointer["run_id"] == "r1"
    receipts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (ads_root / "_validation_receipts").glob("*.json")
    ]
    assert all(receipt.get("validation_run_id") != "r2" for receipt in receipts)
    assert not list(ads_root.glob(".validation-*.tmp"))

    monkeypatch.setattr(crypto_warehouse, "_promote_validation_pointer", real_promote)
    commit("r2", "monitoring", {"lower": 0.9, "upper": 1.1})
    commit("r3", "monitoring", {"lower": 0.9, "upper": 1.1})
    active = pd.read_parquet(ads_root / "ads_crypto_volatility_validation.parquet")
    active = active.loc[active["is_active"].fillna(False).astype(bool)]
    assert len(active) == 1
    assert active.iloc[0]["run_id"] == "r3"
    assert active.iloc[0]["active_signal_status"] == "monitoring"
    assert int(active.iloc[0]["consecutive_null_crossings"]) == 2


def test_ads_recovery_discards_a_partial_pre_replace_journal(tmp_path: Path) -> None:
    abandoned = tmp_path / "warehouse" / "ads" / ".validation-broken.tmp"
    abandoned.mkdir(parents=True)
    (abandoned / "transaction.json").write_text('{"run_id":', encoding="utf-8")

    _commit_crypto_validation_outputs(
        tmp_path,
        data_assurance={"run_id": "data-r1", "data_readiness": "ready", "gates": []},
        validation={
            "run_id": "r1",
            "status": "insufficient_data",
            "data_readiness": "ready",
            "reasons": ["MINIMUM_EVENT_COUNT_NOT_MET"],
        },
        reconciliation=pd.DataFrame(),
        dry_run=False,
    )

    assert not abandoned.exists()


def test_crypto_profile_cli_persists_four_ads_tables_idempotently(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    from trade_py.data.warehouse import crypto as crypto_warehouse

    service = _ready_service(tmp_path)
    sync = service.sync(as_of=_AS_OF)
    assert sync["data_readiness"] == "ready"
    real_service = BtcMarketDataService
    monkeypatch.setattr(
        crypto_warehouse,
        "BtcMarketDataService",
        lambda data_root, **_kwargs: real_service(data_root, now=lambda: _AS_OF),
    )
    command = [
        "warehouse",
        "validate-research",
        "--profile",
        "crypto-btc-v1",
        "--data-root",
        str(tmp_path),
        "--as-of",
        "latest-common",
        "--json",
    ]

    assert data_cli.main(command) == 0
    first = json.loads(capsys.readouterr().out)
    first_frames = {
        table: pd.read_parquet(path)
        for table, path in first["outputs"].items()
    }
    assert first["profile"] == "crypto-btc-v1"
    assert first["validation"]["data_readiness"] == "ready"
    assert first["validation"]["status"] == "insufficient_data"
    assert set(first_frames) == {
        "ads_crypto_data_readiness_report",
        "ads_crypto_provider_reconciliation",
        "ads_crypto_volatility_validation",
        "ads_research_validation_run",
    }
    assert len(first_frames["ads_crypto_provider_reconciliation"]) == 3
    readiness_health = json.loads(
        first_frames["ads_crypto_data_readiness_report"].iloc[0]["data_health_json"]
    )
    run_audit_health = json.loads(
        first_frames["ads_research_validation_run"].iloc[0]["data_health_json"]
    )
    assert readiness_health["data_readiness"] == "ready"
    assert readiness_health["source_stability"]["status"] == "pass"
    assert readiness_health["cross_source_validation"]["aligned_rows"] == 3
    assert run_audit_health["observed"]["watermark"] == "2026-01-09"
    assert all(
        len(frame) == 1
        for table, frame in first_frames.items()
        if table != "ads_crypto_provider_reconciliation"
    )

    assert data_cli.main(command) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["validation"]["run_id"] == first["validation"]["run_id"]
    for table, path in replay["outputs"].items():
        pd.testing.assert_frame_equal(
            pd.read_parquet(path),
            first_frames[table],
            check_dtype=False,
        )
    assert sorted(
        path.name for path in (tmp_path / "warehouse" / "ads").glob("*.parquet")
    ) == [
        "ads_crypto_data_readiness_report.parquet",
        "ads_crypto_provider_reconciliation.parquet",
        "ads_crypto_volatility_validation.parquet",
        "ads_research_validation_run.parquet",
    ]
