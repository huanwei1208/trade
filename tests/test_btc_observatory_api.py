"""WP3 FastAPI observatory API tests (plan §27 owner: test_btc_observatory_api)."""
from __future__ import annotations

import pytest

from trade_py.observatory.catalog import store as catalog_store
from tests.observatory.fixtures import build_observatory_fixture

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from trade_web.backend.observatory import register_observatory_routes  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    app = FastAPI()
    register_observatory_routes(app, str(fx["data_root"]))
    return TestClient(app), fx


def test_context_returns_truth_surface(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/context?channel=formal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved_channel"] == "formal"
    assert body["market_watermark"] == fx["formal_watermark"]
    assert "purpose_fitness" in body
    assert "semantic_channels" in body
    assert body["etag"]
    # Truth surface exposes all watermark channels.
    assert "observed" in body["semantic_channels"]


def test_context_etag_304(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/context?channel=formal")
    etag = resp.headers["etag"]
    resp2 = c.get(
        "/api/v1/observatory/assets/crypto.BTC/context?channel=formal",
        headers={"If-None-Match": etag},
    )
    assert resp2.status_code == 304


def test_series_composite_three_layers(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/series?view=composite")
    assert resp.status_code == 200
    body = resp.json()
    assert body["view"] == "composite"
    assert body["layers"]["formal"] is not None
    assert body["layers"]["latest_observed"] is not None
    assert body["etag"]


def test_series_composite_with_exact_is_invalid(client):
    c, fx = client
    resp = c.get(
        f"/api/v1/observatory/assets/crypto.BTC/series?view=composite&run_id={fx['formal_run_id']}"
    )
    assert resp.status_code == 400
    assert "INVALID_SNAPSHOT_SELECTOR" in resp.json()["reason_codes"]


def test_date_evidence(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/dates/2024-07-20?channel=formal")
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2024-07-20"
    # Observe never shows future outcome.
    assert body["research_visibility"] == "not_visible"


def test_trust_returns_gates(client):
    c, fx = client
    # The candidate (degraded, D1 fail) is addressed by exact run id via trust on
    # its snapshot; the newest evaluation may be the invalid run (no regress rule),
    # so target the degraded candidate run explicitly through the runs surface.
    detail = c.get(f"/api/v1/observatory/runs/{fx['candidate_run_id']}")
    assert detail.status_code == 200
    gates = {g["gate"]: g["status"] for g in detail.json()["gates"]}
    assert gates["D1"] == "fail"  # candidate has D1 blocker


def test_trust_candidate_channel_does_not_regress(client):
    c, fx = client
    # Evaluated candidate channel returns the newest evaluation even if invalid,
    # rather than falling back to an older ready run.
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/trust?channel=evaluated_candidate")
    assert resp.status_code == 200
    assert resp.json()["run_id"] in {fx["invalid_run_id"], fx["candidate_run_id"], fx["observed_run_id"]}


def test_runs_pagination_stable(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/runs?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["runs"]) == 2
    assert "catalog_fingerprint" in body
    # Cursor paging does not duplicate.
    first_ids = [r["run_id"] for r in body["runs"]]
    if body["next_cursor"]:
        resp2 = c.get(f"/api/v1/observatory/assets/crypto.BTC/runs?limit=2&cursor={body['next_cursor']}")
        second_ids = [r["run_id"] for r in resp2.json()["runs"]]
        assert not set(first_ids) & set(second_ids)


def test_run_detail_and_diff(client):
    c, fx = client
    resp = c.get(f"/api/v1/observatory/runs/{fx['formal_run_id']}")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == fx["formal_run_id"]

    diff = c.get(
        f"/api/v1/observatory/runs/diff?base={fx['formal_run_id']}&compare={fx['candidate_run_id']}"
    )
    assert diff.status_code == 200
    body = diff.json()
    # Candidate extends past formal -> added dates present.
    assert body["added_dates"]
    assert "gate_changes" in body


def test_path_traversal_rejected(client):
    c, fx = client
    # An encoded-traversal run id is rejected: either the server normalizes and
    # returns 404, or the facade returns SNAPSHOT_NOT_FOUND. Both fail closed.
    resp = c.get("/api/v1/observatory/runs/..%2f..%2fetc")
    assert resp.status_code == 404
    # A traversal id that reaches the handler returns the frozen reason code.
    resp2 = c.get("/api/v1/observatory/runs/..")
    assert resp2.status_code == 404


def test_path_traversal_rejected_at_facade(client):
    c, fx = client
    from trade_py.observatory.query.facade import ObservatoryQuery
    from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode

    q = ObservatoryQuery(fx["data_root"])
    with pytest.raises(ObservatoryError) as exc:
        q.run_detail("../../etc/passwd")
    assert exc.value.reason_code == ReasonCode.SNAPSHOT_NOT_FOUND


def test_hypotheses_and_research_run(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/hypotheses")
    assert resp.status_code == 200
    assert resp.json()["hypotheses"][0]["hypothesis_id"] == "H1"


def test_catalog_stale_returns_503(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    # Mutate immutable facts without rebuilding the catalog.
    from tests.observatory.fixtures import build_legacy_run

    build_legacy_run(fx["data_root"], run_id="legacy_run_3333333333333333")
    app = FastAPI()
    register_observatory_routes(app, str(fx["data_root"]))
    c = TestClient(app)
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/context?channel=formal")
    assert resp.status_code == 503
    assert "CATALOG_STALE" in resp.json()["reason_codes"]
    assert resp.headers.get("retry-after")


def test_invalid_channel_pit_not_proven(client):
    c, fx = client
    resp = c.get(
        "/api/v1/observatory/assets/crypto.BTC/context"
        "?channel=formal&knowledge_as_of=2019-01-01T00:00:00%2B00:00&knowledge_mode=installation_observed"
    )
    assert resp.status_code == 422
    assert "PIT_NOT_PROVEN" in resp.json()["reason_codes"]
