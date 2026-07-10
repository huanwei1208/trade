from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from trade_py.data.market.cross_asset import store as store_module
from trade_py.data.market.cross_asset.assurance import (
    BtcAssuranceConfig,
    BtcAssuranceResult,
    assure_btc,
    compare_revisions,
    reconcile_btc,
)
from trade_py.data.market.cross_asset.store import BtcRunStore, file_sha256


_FETCHED_AT = pd.Timestamp("2025-01-04T12:00:00Z")


def _primary_frame(
    closes: list[float],
    *,
    start: str = "2025-01-01",
    run_id: str = "fixture-primary",
) -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(closes), freq="D", tz="UTC")
    close = pd.Series(closes, dtype="float64")
    return pd.DataFrame(
        {
            "provider": "okx",
            "venue": "okx",
            "instrument": "BTC-USDT",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "interval": "1Dutc",
            "bar_open_at": dates,
            "bar_close_at": dates + pd.Timedelta(days=1),
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": [1000.0 + index for index in range(len(closes))],
            "is_final": True,
            "fetched_at": _FETCHED_AT,
            "available_at": dates + pd.Timedelta(days=1),
            "payload_hash": [
                hashlib.sha256(f"primary-{index}".encode()).hexdigest()
                for index in range(len(closes))
            ],
            "schema_version": "btc-provider-v1",
            "run_id": run_id,
        }
    )


def _shadow_frame(
    closes: list[float],
    *,
    start: str = "2025-01-01",
    run_id: str = "fixture-shadow",
) -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "provider": "coingecko",
            "venue": "coingecko",
            "instrument": "BTC-USD",
            "base_asset": "BTC",
            "quote_asset": "USD",
            "interval": "daily",
            "bar_open_at": dates,
            "bar_close_at": dates + pd.Timedelta(days=1),
            "close": pd.Series(closes, dtype="float64"),
            "volume": [2000.0 + index for index in range(len(closes))],
            "is_final": True,
            "fetched_at": _FETCHED_AT,
            "available_at": dates + pd.Timedelta(days=1),
            "payload_hash": [
                hashlib.sha256(f"shadow-{index}".encode()).hexdigest()
                for index in range(len(closes))
            ],
            "schema_version": "btc-provider-v1",
            "run_id": run_id,
        }
    )


def _small_ready_config(days: int = 3) -> BtcAssuranceConfig:
    return BtcAssuranceConfig(
        minimum_history_days=days,
        recent_window_days=days,
        recent_coverage_required=1.0,
        full_coverage_required=1.0,
        shadow_days=days,
        shadow_required_days=days,
        acquisition_window_days=days,
        minimum_successful_acquisition_days=1,
        minimum_revision_overlap_days=0,
    )


def _gate(result: BtcAssuranceResult, name: str):
    return next(gate for gate in result.gates if gate.gate == name)


def _ready_result(
    close: float,
    *,
    predecessor: dict[str, object] | None = None,
) -> BtcAssuranceResult:
    closes = [close, close, close]
    result = assure_btc(
        _primary_frame(closes),
        _shadow_frame(closes),
        config=_small_ready_config(),
        acquisition_evidence={
            "attempted": 2,
            "succeeded": 2,
            "daily_attempts": [{"date": "2025-01-04", "qualified": True}],
            "predecessor": predecessor or {"status": "missing", "sha256": None},
        },
        raw_payloads={
            "okx": (b'{"fixture":"okx"}',),
            "coingecko": (b'{"fixture":"coingecko"}',),
        },
    )
    assert result.data_readiness == "ready"
    assert result.publishable is True
    return result


def _seed_current(store: BtcRunStore) -> tuple[str, str]:
    store.cross_asset_root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-12-30", "2024-12-31"]),
            "open": [90.0, 91.0],
            "high": [91.0, 92.0],
            "low": [89.0, 90.0],
            "close": [90.5, 91.5],
        }
    ).to_parquet(store.compatibility_path, index=False)
    old_payload = {
        "run_id": "old-current",
        "canonical_path": str(store.compatibility_path),
        "canonical_sha256": file_sha256(store.compatibility_path),
    }
    store.current_path.write_text(
        json.dumps(old_payload, sort_keys=True),
        encoding="utf-8",
    )
    return file_sha256(store.compatibility_path), store.current_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("target", "column", "mixed_value"),
    [
        ("primary", "provider", "coingecko"),
        ("primary", "quote_asset", "USD"),
        ("primary", "interval", "daily"),
        ("shadow", "provider", "okx"),
        ("shadow", "quote_asset", "USDT"),
        ("shadow", "interval", "1Dutc"),
    ],
)
def test_d0_rejects_provider_quote_and_interval_mixing(
    target: str,
    column: str,
    mixed_value: str,
) -> None:
    primary = _primary_frame([100.0, 100.0, 100.0])
    shadow = _shadow_frame([100.0, 100.0, 100.0])
    frame = primary if target == "primary" else shadow
    frame.loc[1, column] = mixed_value

    result = assure_btc(primary, shadow, config=_small_ready_config())

    gate = _gate(result, "D0")
    assert gate.status == "fail"
    assert gate.reason_code == "INVALID_SCHEMA"
    assert gate.metrics[f"{target}_contract_violations"][column] == 1
    assert result.data_readiness == "invalid"
    assert result.publishable is False


@pytest.mark.parametrize(
    ("case", "metric"),
    [
        ("duplicate", "duplicate_keys"),
        ("null", "null_close"),
        ("nonpositive", "nonpositive_close"),
        ("ohlc", "ohlc_relationship"),
        ("future", "future_completed_bars"),
        ("partial", "non_final_rows"),
    ],
)
def test_d2_rejects_structurally_invalid_primary_rows(case: str, metric: str) -> None:
    primary = _primary_frame([100.0, 100.0, 100.0])
    shadow = _shadow_frame([100.0, 100.0, 100.0])
    if case == "duplicate":
        primary = pd.concat([primary, primary.iloc[[1]]], ignore_index=True)
    elif case == "null":
        primary.loc[1, "close"] = None
    elif case == "nonpositive":
        primary.loc[1, "close"] = 0.0
    elif case == "ohlc":
        primary.loc[1, "high"] = 99.0
    elif case == "future":
        primary.loc[1, "bar_close_at"] = pd.Timestamp("2099-01-02T00:00:00Z")
    elif case == "partial":
        primary.loc[1, "is_final"] = False

    result = assure_btc(primary, shadow, config=_small_ready_config())

    gate = _gate(result, "D2")
    assert gate.status == "fail"
    assert gate.reason_code == "STRUCTURE_INVALID"
    assert gate.metrics["violations"][metric] >= 1
    assert result.data_readiness == "invalid"
    assert result.publishable is False


@pytest.mark.parametrize(
    ("basis_pct", "status", "reason_code"),
    [
        (0.0, "pass", "SOURCE_ALIGNED"),
        (0.5, "pass", "SOURCE_ALIGNED"),
        (0.75, "warn", "SOURCE_DIVERGENCE_WARN"),
        (1.0, "warn", "SOURCE_DIVERGENCE_WARN"),
        (1.25, "block", "SOURCE_DIVERGENCE_BLOCK"),
    ],
)
def test_d3_classifies_basis_thresholds(
    basis_pct: float,
    status: str,
    reason_code: str,
) -> None:
    primary_close = 100.0
    shadow_close = primary_close / (1.0 + basis_pct / 100.0)

    reconciliation = reconcile_btc(
        _primary_frame([primary_close]),
        _shadow_frame([shadow_close]),
        BtcAssuranceConfig(),
    )

    assert len(reconciliation) == 1
    assert reconciliation.loc[0, "basis_pct"] == pytest.approx(basis_pct)
    assert reconciliation.loc[0, "status"] == status
    assert reconciliation.loc[0, "reason_code"] == reason_code


def test_d3_retains_anomaly_when_shadow_confirms_the_move() -> None:
    reconciliation = reconcile_btc(
        _primary_frame([100.0, 100.0, 130.0]),
        _shadow_frame([100.0, 100.0, 130.0]),
        BtcAssuranceConfig(),
    )

    anomaly = reconciliation.iloc[-1]
    assert anomaly["primary_abs_return_pct"] == pytest.approx(30.0)
    assert bool(anomaly["is_suspect_move"]) is True
    assert anomaly["status"] == "pass"
    assert anomaly["reason_code"] == "ANOMALY_CONFIRMED"


def test_anomaly_threshold_is_past_only_when_future_moves_are_appended() -> None:
    closes = [100.0]
    for index in range(1, 45):
        closes.append(closes[-1] * (1.0 + (0.004 if index % 2 else -0.003)))
    config = BtcAssuranceConfig(
        anomaly_mad_window_days=20,
        anomaly_mad_min_history=5,
    )
    base = reconcile_btc(_primary_frame(closes), _shadow_frame(closes), config)
    extended_closes = closes + [closes[-1] * 1.35, closes[-1] * 0.7]
    extended = reconcile_btc(
        _primary_frame(extended_closes),
        _shadow_frame(extended_closes),
        config,
    )

    pd.testing.assert_series_equal(
        base["robust_cutoff_pct"],
        extended.loc[: len(base) - 1, "robust_cutoff_pct"],
        check_names=False,
    )
    assert base["is_suspect_move"].tolist() == extended.loc[
        : len(base) - 1, "is_suspect_move"
    ].tolist()


def test_stale_but_contiguous_provider_history_cannot_be_ready() -> None:
    primary = _primary_frame([100.0, 101.0, 102.0])
    shadow = _shadow_frame([100.0, 101.0, 102.0])
    stale_fetch = pd.Timestamp("2025-01-10T12:00:00Z")
    primary["fetched_at"] = stale_fetch
    primary["available_at"] = stale_fetch
    shadow["fetched_at"] = stale_fetch
    shadow["available_at"] = stale_fetch

    result = assure_btc(primary, shadow, config=_small_ready_config())

    d1 = _gate(result, "D1")
    assert d1.status == "fail"
    assert d1.metrics["latest_expected_open"] == "2025-01-09"
    assert d1.metrics["staleness_days"] == 6
    assert result.data_readiness != "ready"
    assert result.publishable is False


def test_historical_overlap_does_not_substitute_for_daily_acquisition_stability() -> None:
    config = BtcAssuranceConfig(
        minimum_history_days=3,
        recent_window_days=3,
        recent_coverage_required=1.0,
        full_coverage_required=1.0,
        shadow_days=3,
        shadow_required_days=3,
        acquisition_window_days=3,
        minimum_successful_acquisition_days=2,
        minimum_revision_overlap_days=0,
    )
    primary = _primary_frame([100.0, 101.0, 102.0])
    shadow = _shadow_frame([100.0, 101.0, 102.0])

    one_backfill = assure_btc(primary, shadow, config=config)
    stable_attempts = assure_btc(
        primary,
        shadow,
        config=config,
        acquisition_evidence={
            "daily_attempts": [
                {"date": "2025-01-03", "qualified": True},
                {"date": "2025-01-04", "qualified": True},
            ]
        },
    )

    assert _gate(one_backfill, "D1").reason_code == "ACQUISITION_STABILITY_INSUFFICIENT"
    assert one_backfill.data_readiness == "degraded"
    assert one_backfill.publishable is False
    assert _gate(stable_attempts, "D1").status == "pass"
    assert stable_attempts.data_readiness == "ready"


@pytest.mark.parametrize(
    ("revision_pct", "status", "reason_code"),
    [
        (0.1, "pass", "REVISION_ACCEPTED"),
        (0.2, "pass", "REVISION_ACCEPTED"),
        (0.5, "warn", "REVISION_WARN"),
        (1.0, "warn", "REVISION_WARN"),
        (1.5, "block", "REVISION_BLOCK"),
    ],
)
def test_d4_classifies_revision_thresholds(
    revision_pct: float,
    status: str,
    reason_code: str,
) -> None:
    existing = pd.DataFrame({"date": ["2025-01-01"], "close": [100.0]})
    candidate = pd.DataFrame(
        {"date": ["2025-01-01"], "close": [100.0 * (1.0 + revision_pct / 100.0)]}
    )

    revisions = compare_revisions(candidate, existing, BtcAssuranceConfig())

    assert len(revisions) == 1
    assert revisions.loc[0, "revision_pct"] == pytest.approx(revision_pct)
    assert revisions.loc[0, "status"] == status
    assert revisions.loc[0, "reason_code"] == reason_code


def test_identical_inputs_have_deterministic_run_and_artifact_hashes(tmp_path: Path) -> None:
    primary = _primary_frame([100.0, 101.0, 102.0])
    shadow = _shadow_frame([100.0, 101.0, 102.0])
    config = _small_ready_config()
    first = assure_btc(
        primary,
        shadow,
        config=config,
        acquisition_evidence={"attempted": 3, "successful": 3},
    )
    second = assure_btc(
        primary.iloc[::-1].reset_index(drop=True),
        shadow.iloc[::-1].loc[:, list(reversed(shadow.columns))].reset_index(drop=True),
        config=config,
        acquisition_evidence={"successful": 3, "attempted": 3},
    )

    assert first.run_id == second.run_id
    for key in ("config_hash", "primary_hash", "shadow_hash", "canonical_hash"):
        assert first.manifest[key] == second.manifest[key]

    store = BtcRunStore(tmp_path)
    first_stage = store.stage(first)
    replay_stage = store.stage(second)
    assert replay_stage["already_staged"] is True
    assert replay_stage["artifact_hashes"] == first_stage["artifact_hashes"]


def test_stage_failure_preserves_old_current_and_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = BtcRunStore(tmp_path)
    old_hash, old_current = _seed_current(store)
    result = _ready_result(
        100.0,
        predecessor={"status": "readable", "sha256": old_hash, "run_id": "old-current"},
    )
    original_to_parquet = pd.DataFrame.to_parquet

    def fail_shadow_write(frame, path, *args, **kwargs):
        if Path(path).name == "shadow.parquet":
            raise OSError("injected stage failure")
        return original_to_parquet(frame, path, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_shadow_write)

    with pytest.raises(OSError, match="injected stage failure"):
        store.stage(result)

    assert file_sha256(store.compatibility_path) == old_hash
    assert store.current_path.read_text(encoding="utf-8") == old_current
    assert not store.run_dir(result.run_id).exists()
    assert not (store.runs_root / f".{result.run_id}.stage.tmp").exists()


def test_publish_pointer_failure_restores_old_current_and_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = BtcRunStore(tmp_path)
    old_hash, old_current = _seed_current(store)
    result = _ready_result(
        100.0,
        predecessor={"status": "readable", "sha256": old_hash, "run_id": "old-current"},
    )
    store.stage(result)
    original_replace = store_module.os.replace

    def fail_current_pointer(source, destination):
        if Path(destination) == store.current_path:
            raise OSError("injected current-pointer failure")
        return original_replace(source, destination)

    monkeypatch.setattr(store_module.os, "replace", fail_current_pointer)

    with pytest.raises(OSError, match="injected current-pointer failure"):
        store.publish(result)

    assert file_sha256(store.compatibility_path) == old_hash
    assert store.current_path.read_text(encoding="utf-8") == old_current
    assert not list(store.cross_asset_root.glob(".btc*.tmp"))


def test_publish_cas_rejects_a_predecessor_changed_after_assurance(tmp_path: Path) -> None:
    store = BtcRunStore(tmp_path)
    result = _ready_result(100.0)
    old_hash, old_current = _seed_current(store)

    with pytest.raises(RuntimeError, match="predecessor changed"):
        store.publish(result)

    assert file_sha256(store.compatibility_path) == old_hash
    assert store.current_path.read_text(encoding="utf-8") == old_current


def test_publish_rejects_a_tampered_immutable_staged_run(tmp_path: Path) -> None:
    store = BtcRunStore(tmp_path)
    result = _ready_result(100.0)
    store.stage(result)
    canonical_path = store.run_dir(result.run_id) / "canonical.parquet"
    tampered = pd.read_parquet(canonical_path)
    tampered["close"] = 999.0
    tampered.to_parquet(canonical_path, index=False)

    with pytest.raises(ValueError, match="artifacts are invalid"):
        store.publish(result)

    assert not store.compatibility_path.exists()
    assert not store.current_path.exists()


def test_publish_rejects_a_tampered_staged_manifest_gate_state(tmp_path: Path) -> None:
    store = BtcRunStore(tmp_path)
    result = _ready_result(100.0)
    store.stage(result)
    manifest_path = store.run_dir(result.run_id) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["data_readiness"] = "degraded"
    for gate in manifest["gates"]:
        if gate["gate"] == "D4":
            gate["status"] = "fail"
            gate["reason_code"] = "REVISION_BLOCK"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest:data_readiness"):
        store.publish(result)

    assert not store.compatibility_path.exists()
    assert not store.current_path.exists()


def test_rollback_verifies_hash_then_restores_the_selected_run(tmp_path: Path) -> None:
    store = BtcRunStore(tmp_path)
    old_result = _ready_result(100.0)
    store.publish(old_result)
    old_artifact = store.run_dir(old_result.run_id) / "canonical.parquet"
    old_artifact_bytes = old_artifact.read_bytes()
    old_artifact_hash = file_sha256(old_artifact)
    old_current = store.current()
    new_result = _ready_result(
        200.0,
        predecessor={
            "status": "readable",
            "sha256": file_sha256(store.compatibility_path),
            "run_id": old_current["run_id"],
        },
    )
    store.publish(new_result)
    new_current = store.current_path.read_bytes()
    new_canonical_hash = file_sha256(store.compatibility_path)

    old_artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="rollback canonical hash mismatch"):
        store.rollback(old_result.run_id)
    assert store.current_path.read_bytes() == new_current
    assert file_sha256(store.compatibility_path) == new_canonical_hash

    old_artifact.write_bytes(old_artifact_bytes)
    payload = store.rollback(old_result.run_id)

    assert payload["run_id"] == old_result.run_id
    assert payload["previous_run_id"] == new_result.run_id
    assert payload["rollback"] is True
    assert Path(payload["rollback_audit_path"]).is_file()
    rollback_audit = json.loads(Path(payload["rollback_audit_path"]).read_text(encoding="utf-8"))
    assert rollback_audit["from_run_id"] == new_result.run_id
    assert rollback_audit["to_run_id"] == old_result.run_id
    assert file_sha256(store.compatibility_path) == old_artifact_hash
    assert store.current()["run_id"] == old_result.run_id
    pd.testing.assert_frame_equal(
        pd.read_parquet(store.compatibility_path),
        old_result.canonical,
        check_dtype=False,
    )


def test_rollback_rejects_an_unpublished_or_non_ready_staged_run(tmp_path: Path) -> None:
    store = BtcRunStore(tmp_path)
    staged = _ready_result(100.0)
    store.stage(staged)

    with pytest.raises(ValueError, match="publication evidence"):
        store.rollback(staged.run_id)

    manifest_path = store.run_dir(staged.run_id) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["data_readiness"] = "degraded"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="originally ready"):
        store.rollback(staged.run_id)


def test_rollback_current_is_rejected_without_losing_the_real_predecessor(
    tmp_path: Path,
) -> None:
    store = BtcRunStore(tmp_path)
    first = _ready_result(100.0)
    store.publish(first)
    first_pointer = store.current()
    second = _ready_result(
        200.0,
        predecessor={
            "status": "readable",
            "sha256": file_sha256(store.compatibility_path),
            "run_id": first_pointer["run_id"],
        },
    )
    store.publish(second)
    pointer_before = store.current_path.read_bytes()

    with pytest.raises(ValueError, match="already the current"):
        store.rollback(second.run_id)

    assert store.current_path.read_bytes() == pointer_before
    restored = store.rollback_predecessor()
    assert restored["run_id"] == first.run_id
    assert store.current()["run_id"] == first.run_id


def test_first_publish_can_restore_the_exact_legacy_predecessor(tmp_path: Path) -> None:
    store = BtcRunStore(tmp_path)
    store.cross_asset_root.mkdir(parents=True)
    legacy = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-12-30", "2024-12-31"]),
            "open": [90.0, 91.0],
            "high": [91.0, 92.0],
            "low": [89.0, 90.0],
            "close": [90.5, 91.5],
        }
    )
    legacy.to_parquet(store.compatibility_path, index=False)
    legacy_bytes = store.compatibility_path.read_bytes()
    legacy_hash = file_sha256(store.compatibility_path)
    result = _ready_result(
        100.0,
        predecessor={"status": "readable", "sha256": legacy_hash, "run_id": None},
    )

    published = store.publish(result)
    restored = store.rollback_predecessor()

    assert published["current"]["predecessor_sha256"] == legacy_hash
    assert restored["reason_code"] == "LEGACY_LINEAGE_MISSING"
    assert store.compatibility_path.read_bytes() == legacy_bytes
    assert not store.current_path.exists()
    assert Path(restored["rollback_audit_path"]).is_file()

    store.rollback(result.run_id)
    restored_again = store.rollback_predecessor()
    assert restored_again["reason_code"] == "LEGACY_LINEAGE_MISSING"
    assert store.compatibility_path.read_bytes() == legacy_bytes


def test_publish_rebuilds_a_corrupt_existing_predecessor_snapshot(tmp_path: Path) -> None:
    store = BtcRunStore(tmp_path)
    store.cross_asset_root.mkdir(parents=True)
    legacy = pd.DataFrame({"date": pd.to_datetime(["2024-12-31"]), "close": [91.5]})
    legacy.to_parquet(store.compatibility_path, index=False)
    legacy_bytes = store.compatibility_path.read_bytes()
    legacy_hash = file_sha256(store.compatibility_path)
    backup = store.runs_root / "_predecessors" / f"{legacy_hash}.parquet"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"partial")
    result = _ready_result(
        100.0,
        predecessor={"status": "readable", "sha256": legacy_hash, "run_id": None},
    )

    store.publish(result)
    restored = store.rollback_predecessor()

    assert file_sha256(backup) == legacy_hash
    assert restored["reason_code"] == "LEGACY_LINEAGE_MISSING"
    assert store.compatibility_path.read_bytes() == legacy_bytes
