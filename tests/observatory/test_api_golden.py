"""WP3.2 OpenAPI golden contract tests.

Assert the response SHAPE (key sets and frozen enums) is stable against committed
goldens, without pinning volatile values (rendered_at, hashes, fingerprints).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_py.observatory.catalog import store as catalog_store
from tests.observatory.fixtures import build_observatory_fixture

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from trade_web.backend.observatory import register_observatory_routes  # noqa: E402

GOLDEN = Path(__file__).parent / "golden"
_VOLATILE = {
    "rendered_at", "etag", "view_fingerprint", "snapshot_id", "fingerprint_basis",
    "catalog_fingerprint", "effective_knowledge_cut", "evidence_refs",
}


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: ("<VOLATILE>" if k in _VOLATILE else _scrub(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _keys(obj):
    """Recursive key structure (order-independent) for shape comparison."""

    if isinstance(obj, dict):
        return {k: _keys(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [_keys(obj[0])] if obj else []
    return type(obj).__name__


@pytest.fixture()
def client(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    app = FastAPI()
    register_observatory_routes(app, str(fx["data_root"]))
    return TestClient(app), fx


def test_context_formal_shape_matches_golden(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/context?channel=formal")
    golden = json.loads((GOLDEN / "context_formal_success.json").read_text())
    assert _keys(_scrub(resp.json())) == _keys(golden)


def test_context_candidate_shape_matches_golden(client):
    c, fx = client
    resp = c.get("/api/v1/observatory/assets/crypto.BTC/context?channel=evaluated_candidate")
    golden = json.loads((GOLDEN / "context_candidate_degraded.json").read_text())
    assert _keys(_scrub(resp.json())) == _keys(golden)


def test_error_selector_shape_matches_golden(client):
    c, fx = client
    resp = c.get(
        f"/api/v1/observatory/assets/crypto.BTC/series?view=composite&run_id={fx['formal_run_id']}"
    )
    golden = json.loads((GOLDEN / "error_invalid_selector.json").read_text())
    assert resp.status_code == golden["status"]
    assert _keys(_scrub(resp.json())) == _keys(golden["body"])
    assert resp.json()["reason_codes"] == golden["body"]["reason_codes"]


def test_route_inventory_is_stable(client):
    c, fx = client
    # Guard against accidental route additions/removals.
    from trade_web.backend.observatory import register_observatory_routes as reg

    app = FastAPI()
    reg(app, str(fx["data_root"]))
    paths = sorted({r.path for r in app.routes if "observatory" in getattr(r, "path", "")})
    assert paths == [
        "/api/v1/observatory/assets/crypto.BTC/context",
        "/api/v1/observatory/assets/crypto.BTC/dates/{market_date}",
        "/api/v1/observatory/assets/crypto.BTC/hypotheses",
        "/api/v1/observatory/assets/crypto.BTC/runs",
        "/api/v1/observatory/assets/crypto.BTC/series",
        "/api/v1/observatory/assets/crypto.BTC/trust",
        "/api/v1/observatory/research-runs/{research_run_id}",
        "/api/v1/observatory/runs/diff",
        "/api/v1/observatory/runs/{run_id}",
    ]
