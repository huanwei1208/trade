from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from trade_py.db.trade_db import _EVENT_LOG_REPLAYABLE_SQL, TradeDB


def _make_stale_claim(
    db: TradeDB,
    *,
    topic: str,
    handler_name: str,
    claim_token: str,
) -> int:
    event_id = db.event_log_insert(topic, "{}")
    db.prepare_handler_runs(event_id, [handler_name])
    assert db.claim_handler_run(event_id, handler_name, claim_token)
    with db._conn_lock:
        db._conn.execute(
            """
            UPDATE event_handler_runs
            SET started_at=datetime('now', 'localtime', '-10 minutes')
            WHERE event_id=? AND handler_name=?
            """,
            (event_id, handler_name),
        )
        db._conn.commit()
    return event_id


def _current_process_start_ticks() -> int:
    stat_text = open(f"/proc/{os.getpid()}/stat", encoding="utf-8").read()
    start_ticks = TradeDB._linux_proc_start_ticks(stat_text)
    assert start_ticks is not None
    return start_ticks


def test_replay_uses_only_reserved_runtime_admission_provenance(tmp_path) -> None:
    db = TradeDB(tmp_path)
    runtime_event = db.event_log_insert("ops.runtime", "{}")
    legacy_event = db.event_log_insert("ops.legacy", "{}")
    business_event = db.event_log_insert("ops.business", "{}")
    dag_handoff_event = db.event_log_insert("gate.manual", "{}")
    for event_id, handler_name in (
        (runtime_event, "tests.runtime"),
        (legacy_event, "tests.legacy"),
        (business_event, "tests.business"),
        (dag_handoff_event, "dag.fetch.fixture.row_1"),
    ):
        db.prepare_handler_runs(event_id, [handler_name])

    db.mark_handler_admission_failed(
        runtime_event,
        "tests.runtime",
        "submission_failed: executor unavailable",
    )
    db.mark_handler_error(
        legacy_event,
        "tests.legacy",
        "submission_failed: historical handler exception",
        1,
    )
    db.mark_handler_error(
        business_event,
        "tests.business",
        "provider rejected request",
        1,
    )
    db.mark_handler_error(
        dag_handoff_event,
        "dag.fetch.fixture.row_1",
        "submission_failed: DAG child handoff topic=ops.child",
        1,
    )

    runtime_row = db.get_handler_run(runtime_event, "tests.runtime")
    assert runtime_row is not None
    assert runtime_row["error_message"] == (
        "runtime_admission:submission_failed: executor unavailable"
    )
    assert [row["id"] for row in db.event_log_replayable()] == [
        runtime_event,
        dag_handoff_event,
    ]
    assert db.replayable_handler_names(runtime_event) == {"tests.runtime"}
    assert db.replayable_handler_names(legacy_event) == set()
    assert db.replayable_handler_names(business_event) == set()
    assert db.replayable_handler_names(dag_handoff_event) == {"dag.fetch.fixture.row_1"}
    db.close()


def test_sparse_replay_query_uses_existing_status_and_event_indexes(tmp_path) -> None:
    db = TradeDB(tmp_path)
    with db._conn_lock:
        db._conn.executemany(
            """
            INSERT INTO event_log
                (topic, payload, status, handler, created_at, processed_at)
            VALUES ('history.complete', '{}', 'ok', '<fixture>',
                    datetime('now', 'localtime'), datetime('now', 'localtime'))
            """,
            [() for _ in range(5000)],
        )
        pending_event = db.event_log_insert("ops.pending", "{}")
        plan_rows = db._conn.execute(
            f"EXPLAIN QUERY PLAN {_EVENT_LOG_REPLAYABLE_SQL}",
            {
                "after_id": 0,
                "stale_modifier": "-120 seconds",
                "limit": 100,
            },
        ).fetchall()

    assert [row["id"] for row in db.event_log_replayable()] == [pending_event]
    plan = "\n".join(str(row["detail"]) for row in plan_rows)
    assert "idx_event_status" in plan
    assert "idx_event_handler_runs_status" in plan
    assert "idx_event_handler_runs_event" in plan
    assert "SCAN event_log" not in plan
    db.close()


@pytest.mark.skipif(not os.path.exists("/proc/self/stat"), reason="requires Linux /proc identity")
def test_stale_claim_refuses_reclaim_while_process_identity_is_alive(tmp_path) -> None:
    db = TradeDB(tmp_path)
    owner_token = f"process:{os.getpid()}:{_current_process_start_ticks()}:{uuid4()}"
    event_id = _make_stale_claim(
        db,
        topic="ops.live-owner",
        handler_name="tests.live-owner",
        claim_token=owner_token,
    )

    assert (
        db.claim_handler_run(
            event_id,
            "tests.live-owner",
            f"process:{os.getpid()}:{_current_process_start_ticks()}:{uuid4()}",
            stale_after_seconds=1,
        )
        is False
    )
    row = db.get_handler_run(event_id, "tests.live-owner")
    assert row is not None
    assert row["error_message"] == f"claim:{owner_token}"
    db.close()


@pytest.mark.skipif(not os.path.exists("/proc/self/stat"), reason="requires Linux /proc identity")
def test_stale_claim_reclaims_dead_or_reused_process_identity(tmp_path) -> None:
    db = TradeDB(tmp_path)
    current_ticks = _current_process_start_ticks()
    cases = [
        ("dead", f"process:2147483647:1:{uuid4()}"),
        ("reused", f"process:{os.getpid()}:{current_ticks + 1}:{uuid4()}"),
    ]

    for label, owner_token in cases:
        handler_name = f"tests.{label}"
        event_id = _make_stale_claim(
            db,
            topic=f"ops.{label}",
            handler_name=handler_name,
            claim_token=owner_token,
        )
        assert db.claim_handler_run(
            event_id,
            handler_name,
            f"process:{os.getpid()}:{current_ticks}:{uuid4()}",
            stale_after_seconds=1,
        )
    db.close()


def test_stale_claim_fails_closed_for_malformed_process_identity(tmp_path) -> None:
    db = TradeDB(tmp_path)
    event_id = _make_stale_claim(
        db,
        topic="ops.malformed-owner",
        handler_name="tests.malformed-owner",
        claim_token="process:not-a-pid:not-ticks:missing-proof",
    )

    assert (
        db.claim_handler_run(
            event_id,
            "tests.malformed-owner",
            "replacement",
            stale_after_seconds=1,
        )
        is False
    )
    db.close()


def test_legacy_stale_claim_preserves_lease_timeout_recovery(tmp_path) -> None:
    db = TradeDB(tmp_path)
    event_id = _make_stale_claim(
        db,
        topic="ops.legacy-owner",
        handler_name="tests.legacy-owner",
        claim_token="legacy-runtime-token",
    )

    assert db.claim_handler_run(
        event_id,
        "tests.legacy-owner",
        "replacement",
        stale_after_seconds=1,
    )
    db.close()


def test_dead_claim_reclaim_is_atomic_across_connections(tmp_path) -> None:
    first_db = TradeDB(tmp_path)
    second_db = TradeDB(tmp_path)
    event_id = _make_stale_claim(
        first_db,
        topic="ops.atomic-reclaim",
        handler_name="tests.atomic-reclaim",
        claim_token=f"process:2147483647:1:{uuid4()}",
    )

    def claim(db: TradeDB, token: str) -> bool:
        return db.claim_handler_run(
            event_id,
            "tests.atomic-reclaim",
            token,
            stale_after_seconds=1,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                claim,
                (first_db, second_db),
                ("replacement:first", "replacement:second"),
            )
        )

    assert sorted(results) == [False, True]
    first_db.close()
    second_db.close()


def test_event_log_get_or_insert_once_is_durable_across_connections(tmp_path) -> None:
    first_db = TradeDB(tmp_path)
    second_db = TradeDB(tmp_path)

    def persist(db: TradeDB) -> tuple[dict, bool]:
        return db.event_log_get_or_insert_once(
            "agenda.open",
            '{"phase":"open"}',
            "agenda:2026-07-21:open",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(persist, (first_db, second_db)))

    assert sorted(created for _row, created in results) == [False, True]
    assert len({int(row["id"]) for row, _created in results}) == 1
    assert [row["id"] for row in first_db.event_log_replayable()] == [
        results[0][0]["id"],
    ]
    repeated, created = first_db.event_log_get_or_insert_once(
        "agenda.open",
        '{ "phase": "open" }',
        "agenda:2026-07-21:open",
    )
    assert created is False
    assert repeated["payload"] == '{"phase":"open"}'
    with pytest.raises(RuntimeError, match="idempotent event payload conflict"):
        first_db.event_log_get_or_insert_once(
            "agenda.open",
            '{"phase":"changed-but-same-identity"}',
            "agenda:2026-07-21:open",
        )
    typed, typed_created = first_db.event_log_get_or_insert_once(
        "agenda.typed",
        '{"values":[true]}',
        "agenda:2026-07-21:typed",
    )
    assert typed_created is True
    assert typed["payload"] == '{"values":[true]}'
    with pytest.raises(RuntimeError, match="idempotent event payload conflict"):
        first_db.event_log_get_or_insert_once(
            "agenda.typed",
            '{"values":[1]}',
            "agenda:2026-07-21:typed",
        )
    parent_id = first_db.event_log_insert("agenda.parent", "{}")
    child, child_created = first_db.event_log_get_or_insert_once(
        "agenda.open",
        '{"phase":"open"}',
        "agenda:2026-07-21:open",
        parent_event_id=parent_id,
    )
    assert child_created is True
    assert child["parent_event_id"] == parent_id
    first_db.close()
    second_db.close()


def test_child_handoff_payload_conflict_fails_closed(tmp_path) -> None:
    db = TradeDB(tmp_path)
    parent_id = db.event_log_insert("agenda.parent", "{}")
    first, created = db.event_log_get_or_insert_child(
        "agenda.child",
        '{"value":1}',
        parent_id,
        "agenda:1:child",
    )

    assert created is True
    repeated, repeated_created = db.event_log_get_or_insert_child(
        "agenda.child",
        '{ "value": 1 }',
        parent_id,
        "agenda:1:child",
    )
    assert repeated_created is False
    assert repeated["id"] == first["id"]
    with pytest.raises(RuntimeError, match="idempotent event payload conflict"):
        db.event_log_get_or_insert_child(
            "agenda.child",
            '{"value":2}',
            parent_id,
            "agenda:1:child",
        )
    with pytest.raises(RuntimeError, match="idempotent event payload conflict"):
        db.event_log_get_or_insert_child(
            "agenda.child",
            '{"value":true}',
            parent_id,
            "agenda:1:child",
        )
    db.close()


def test_readiness_signature_components_preserve_optional_table_defaults(tmp_path) -> None:
    db = TradeDB(tmp_path)

    defaults = db.readiness_signature_components()

    assert len(defaults) == 13
    assert defaults[5] == 0
    assert defaults[6] == ""
    with db._conn_lock:
        db._conn.executescript(
            """
            CREATE TABLE data_repair_runs (id INTEGER PRIMARY KEY);
            CREATE TABLE data_gaps (updated_at TEXT);
            INSERT INTO data_repair_runs(id) VALUES (41);
            INSERT INTO data_gaps(updated_at) VALUES ('2026-07-21 12:30:00');
            """
        )
        db._conn.commit()

    populated = db.readiness_signature_components()

    assert populated[5] == 41
    assert populated[6] == "2026-07-21 12:30:00"
    db.close()


def test_named_runtime_projections_preserve_web_read_contracts(tmp_path) -> None:
    db = TradeDB(tmp_path)
    as_of = "2026-07-21"
    db.upsert_instrument("AAA.SH", "Alpha")
    db.upsert_instrument("BBB.SH", "Beta")
    db.upsert_instrument("CCC.SH", "")
    db.replace_sector_members(
        [
            ("AAA.SH", "SEC-1", "Clean Energy", 1),
            ("BBB.SH", "SEC-1", "Clean Energy", 1),
            ("CCC.SH", "SEC-1", "Clean Energy", 1),
        ]
    )
    for row in (
        {
            "event_id": "sector-event",
            "event_date": as_of,
            "event_type": "policy",
            "entity_id": "SEC-1",
            "magnitude": 0.8,
            "confidence": 0.9,
            "sentiment_score": 0.6,
            "news_volume": 4,
            "summary": "sector event",
        },
        {
            "event_id": "macro-event",
            "event_date": "2026-07-20",
            "event_type": "macro",
            "entity_id": "SW_MACRO_RATE",
            "magnitude": 0.4,
            "confidence": 0.7,
            "sentiment_score": -0.2,
            "news_volume": 2,
            "summary": "macro event",
        },
        {
            "event_id": "unrelated-event",
            "event_date": as_of,
            "event_type": "other",
            "entity_id": "SEC-2",
            "magnitude": 0.3,
            "confidence": 0.5,
            "sentiment_score": 0.1,
            "news_volume": 1,
            "summary": "unrelated",
        },
    ):
        db.event_upsert(row)
    db.event_propagation_insert_batch(
        [
            {
                "event_id": "sector-event",
                "symbol": "AAA.SH",
                "hop": 1,
                "kg_score": 0.8,
                "typical_days": 3,
            },
            {
                "event_id": "macro-event",
                "symbol": "AAA.SH",
                "hop": 1,
                "kg_score": 0.4,
                "typical_days": 2,
            },
            {
                "event_id": "sector-event",
                "symbol": "BBB.SH",
                "hop": 1,
                "kg_score": 0.6,
                "typical_days": 3,
            },
        ]
    )
    db.kg_relation_upsert_batch(
        [
            {
                "from_entity": "SEC-1",
                "to_entity": "AAA.SH",
                "rel_type": "contains",
                "weight": 0.8,
                "direction": 1,
                "typical_days": 1,
                "confidence": 0.9,
                "sample_count": 3,
                "source": "fixture",
                "valid_from": None,
                "valid_to": None,
                "evidence_json": "{}",
                "status": "active",
            }
        ]
    )
    db.evidence_upsert(
        "ev-1",
        as_of,
        "AAA.SH",
        "news",
        "article:1",
        0.7,
        -0.5,
        0.8,
        0.6,
        0.1,
        0.0,
    )
    db.quality_report_upsert(
        as_of,
        "ok",
        "ready",
        [],
        {"trust_scalar": 0.8},
    )
    db.quality_gate_upsert(as_of, "ok", [], {"latest_metrics": {"source_healthy_ratio": 0.9}})
    db.sync_state_set(
        "tushare_kline",
        "daily",
        "BBB.SH",
        last_date=as_of,
        row_count=11,
    )
    db.sync_state_set("akshare", "fund_flow", "AAA.SH", last_date="2026-07-20")
    db.sync_state_set("tushare", "fundamental", "AAA.SH", last_date="2026-07-19")
    db.sync_state_set(
        "tushare_kline",
        "daily",
        "AAA.SH",
        last_date=as_of,
        row_count=21,
    )
    db._conn.execute(
        """
        INSERT INTO signals(date, symbol, window_score, net_sentiment)
        VALUES (?, 'BBB.SH', 77, 0.25)
        """,
        (as_of,),
    )
    db._conn.commit()
    db.recommendation_upsert(
        "rec-bbb",
        as_of,
        "BBB.SH",
        "WATCH",
        "medium",
        0.55,
        0.2,
        5,
        [],
    )
    db.belief_state_upsert(
        as_of,
        "BBB.SH",
        {"mu": 0.12},
        "v1",
        0.75,
        0.25,
    )
    db.belief_state_upsert(
        as_of,
        "AAA.SH",
        {"mu": 0.2},
        "v1",
        0.8,
        0.2,
    )
    db.recommendation_upsert(
        "rec-aaa",
        as_of,
        "AAA.SH",
        "ADD",
        "high",
        0.8,
        0.15,
        5,
        [],
    )

    assert db.symbol_event_types("AAA.SH", as_of, 3) == ["policy", "macro"]
    assert db.instrument_names([" aaa.sh ", "BBB.SH", "AAA.SH", "missing"]) == {
        "AAA.SH": "Alpha",
        "BBB.SH": "Beta",
    }
    kg = db.kg_projection_summary(symbol_limit=1)
    assert kg["top_symbols"] == [
        {
            "symbol": "AAA.SH",
            "propagation_count": 2,
            "avg_kg_score": 0.6,
            "latest_event_date": as_of,
        }
    ]
    assert kg["relation_types"] == [{"rel_type": "contains", "relation_count": 1}]
    quality = db.quality_history_projection(limit=1)
    assert quality["reports"][0]["eval_date"] == as_of
    assert quality["gates"][0]["eval_date"] == as_of
    assert db.evidence_lookup("ev-1") == {
        "evidence_type": "news",
        "direction": -0.5,
    }
    assert db.evidence_lookup("missing") is None
    evidence = db.symbol_evidence_projection("AAA.SH", as_of, 7, evidence_limit=20)
    assert evidence["sector_code"] == "SEC-1"
    assert [row["event_id"] for row in evidence["market_events"]] == [
        "sector-event",
        "macro-event",
    ]
    assert evidence["evidence_items"][0]["evidence_id"] == "ev-1"
    sector = db.symbol_sector_peer_projection("AAA.SH", as_of, peer_limit=1)
    assert sector["sector_code"] == "SEC-1"
    assert sector["sector_name"] == "Clean Energy"
    assert sector["sector_sentiment"] == pytest.approx(0.6)
    assert sector["sector_event_count"] == 1
    assert sector["peers"] == [
        {
            "symbol": "BBB.SH",
            "name": "Beta",
            "window_score": 77,
            "net_sentiment": 0.25,
            "action": "WATCH",
            "conviction": "medium",
            "score": 0.55,
            "risk": 0.2,
            "belief_mu": 0.12,
            "belief_confidence": 0.75,
            "kline_last_date": as_of,
        }
    ]
    freshness = db.symbol_data_freshness_projection("AAA.SH", as_of)
    assert freshness == {
        "kline": {"last_date": as_of, "row_count": 21},
        "fund_flow": {"last_date": "2026-07-20"},
        "fundamental": {"last_date": "2026-07-19"},
        "sentiment": {"last_date": as_of},
        "events": {"last_date": as_of, "row_count": 1},
        "belief": {"last_date": as_of},
        "recommend": {"last_date": as_of},
    }
    assert json.loads(quality["reports"][0]["metrics_json"]) == {"trust_scalar": 0.8}
    db.close()
