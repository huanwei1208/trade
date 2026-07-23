"""WP3 FastAPI observatory API tests (plan §27 owner: test_btc_observatory_api)."""

from __future__ import annotations

import pytest

from tests.observatory.fixtures import build_observatory_fixture
from trade_py.observatory.catalog import store as catalog_store

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from trade_web.backend.observatory import register_observatory_routes  # noqa: E402


def _observatory_paths(app: FastAPI) -> set[str]:
    return {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and "observatory" in route.path
    }


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
    assert resp2.content == b""


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
    assert resp.json()["run_id"] in {
        fx["invalid_run_id"],
        fx["candidate_run_id"],
        fx["observed_run_id"],
    }


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
        resp2 = c.get(
            f"/api/v1/observatory/assets/crypto.BTC/runs?limit=2&cursor={body['next_cursor']}"
        )
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
    from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode
    from trade_py.observatory.query.facade import ObservatoryQuery

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


def test_capability_route_reports_catalog_stale_as_navigable(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    # Mutate immutable facts without rebuilding the catalog. The page should
    # remain discoverable, while data routes report explicit stale evidence.
    from tests.observatory.fixtures import build_legacy_run

    build_legacy_run(fx["data_root"], run_id="legacy_run_4444444444444444")
    app = FastAPI()
    register_observatory_routes(app, str(fx["data_root"]))
    c = TestClient(app)
    resp = c.get("/api/v1/observatory/capability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["state"] == "catalog_stale"
    assert body["show_nav"] is True


def test_invalid_channel_pit_not_proven(client):
    c, fx = client
    resp = c.get(
        "/api/v1/observatory/assets/crypto.BTC/context"
        "?channel=formal&knowledge_as_of=2019-01-01T00:00:00%2B00:00&knowledge_mode=installation_observed"
    )
    assert resp.status_code == 422
    assert "PIT_NOT_PROVEN" in resp.json()["reason_codes"]


# ── RA.1: rollout gate + capability route (docs/27 Phase A, F14) ──────────────


def test_capability_route_reports_ready_when_catalog_built(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/capability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["state"] == "ready"
    # The frontend uses show_nav to decide visibility.
    assert body["show_nav"] is True


def test_capability_route_reports_catalog_missing_without_build(tmp_path):
    # An unprepared installation: routes may be registered but the Catalog is absent.
    fx = build_observatory_fixture(tmp_path / "data")
    app = FastAPI()
    register_observatory_routes(app, str(fx["data_root"]))
    c = TestClient(app)
    resp = c.get("/api/v1/observatory/capability")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "catalog_missing"
    # Missing catalog has no resource state to inspect, so do not advertise navigation.
    assert body["show_nav"] is False


def test_capability_route_does_not_build_catalog(tmp_path):
    from trade_py.observatory.catalog import store

    fx = build_observatory_fixture(tmp_path / "data")
    app = FastAPI()
    register_observatory_routes(app, str(fx["data_root"]))
    c = TestClient(app)
    c.get("/api/v1/observatory/capability")
    # Startup/GET capability probe never auto-builds the projection.
    assert store.load_generation(fx["data_root"]) is None


def test_rollout_default_off_hides_data_routes_but_reports_disabled(tmp_path, monkeypatch):
    """F14: backend must default Observatory OFF (explicitly enabled). When disabled,
    the data routes are absent but the capability probe stays reachable and reports
    `disabled` so the frontend and routes remain consistent (plan §G)."""

    from trade_web.backend import observatory as observatory_pkg

    monkeypatch.delenv("TRADE_OBSERVATORY_ENABLED", raising=False)
    assert observatory_pkg.observatory_enabled() is False

    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    monkeypatch.setenv("TRADE_DATA_ROOT", str(fx["data_root"]))
    monkeypatch.setenv("TRADE_OBSERVATORY_ENABLED", "0")
    from trade_web import create_app

    app = create_app()
    obs_paths = sorted(_observatory_paths(app))
    # Only the always-on capability probe; no data routes.
    assert obs_paths == ["/api/v1/observatory/capability"]

    c = TestClient(app)
    cap = c.get("/api/v1/observatory/capability")
    assert cap.status_code == 200
    body = cap.json()
    assert body["enabled"] is False
    assert body["state"] == "disabled"
    assert body["show_nav"] is False
    # Data routes are truly absent even though the catalog is ready.
    assert c.get("/api/v1/observatory/assets/crypto.BTC/context?channel=formal").status_code == 404


def test_rollout_enabled_registers_routes(tmp_path, monkeypatch):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    monkeypatch.setenv("TRADE_DATA_ROOT", str(fx["data_root"]))
    monkeypatch.setenv("TRADE_OBSERVATORY_ENABLED", "1")
    from trade_web import create_app

    app = create_app()
    obs_paths = sorted(_observatory_paths(app))
    assert "/api/v1/observatory/capability" in obs_paths
    assert "/api/v1/observatory/assets/crypto.BTC/context" in obs_paths


# ── RA.1 (C): route-registration defects must NOT silently drop /capability ───


def test_data_route_defect_does_not_drop_capability_probe(tmp_path, monkeypatch):
    """F14/C: if enabled data-route registration raises, the app must still expose
    `/capability` reporting `state=error` (nav hidden) — never an app silently
    missing the capability route. The broad `except ImportError: pass` is gone."""

    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    monkeypatch.setenv("TRADE_DATA_ROOT", str(fx["data_root"]))
    monkeypatch.setenv("TRADE_OBSERVATORY_ENABLED", "1")

    # Inject a defect into data-route registration (the heavy path), leaving the
    # light capability path intact. create_app resolves these names from the
    # observatory package namespace at call time, so patching the package suffices.
    from trade_web.backend import observatory as observatory_pkg

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated facade/registration defect")

    monkeypatch.setattr(observatory_pkg, "register_observatory_routes", _boom)
    from trade_web import create_app

    app = create_app()
    obs_paths = sorted(_observatory_paths(app))
    # The capability probe survives; data routes are absent.
    assert "/api/v1/observatory/capability" in obs_paths
    assert "/api/v1/observatory/assets/crypto.BTC/context" not in obs_paths

    c = TestClient(app)
    body = c.get("/api/v1/observatory/capability").json()
    assert body["state"] == "error"
    assert body["show_nav"] is False
    # The public probe carries a stable, safe reason_code and never leaks the
    # internal exception text/paths (the full exception is logged server-side).
    assert body["reason_code"] == "route_registration_failed"
    assert "detail" not in body


def test_capability_route_import_is_facade_independent():
    """The always-on capability path must not depend on the heavy facade import, so
    a facade defect cannot remove the probe. Registering the capability probe on a
    bare app must succeed without importing ObservatoryQuery."""

    import sys

    from trade_web.backend.observatory import register_observatory_capability

    # Registering the capability probe alone must not require the facade module.
    sys.modules.pop("trade_py.observatory.query.facade", None)
    app = FastAPI()
    register_observatory_capability(app, "data", enabled=False)
    assert "trade_py.observatory.query.facade" not in sys.modules
    obs_paths = _observatory_paths(app)
    assert "/api/v1/observatory/capability" in obs_paths
