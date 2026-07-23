from __future__ import annotations


def test_status_api_exposes_local_data_quality_gate(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    def fake_get_data_status(data_root, sample_limit=8):
        return {
            "as_of": "2026-03-20",
            "quality_gate": {
                "status": "warn",
                "reason_codes": ["KLINE_STALE_OR_LOW_COVERAGE"],
                "components": {
                    "kline": {
                        "status": "warn",
                        "reason_code": "KLINE_STALE_OR_LOW_COVERAGE",
                    }
                },
                "recovery_plan": [
                    {
                        "component": "kline",
                        "command": ["trade", "data", "kline", "sync"],
                        "mode": "refresh",
                        "detail": "Refresh K-line source data and watermarks",
                    }
                ],
            },
        }

    monkeypatch.setenv("TRADE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr("trade_py.utils.data_inspector.get_data_status", fake_get_data_status)

    from trade_web import create_app

    app = create_app()
    with TestClient(app) as client:
        owned_db = app.state.resources.db
        payload = client.get("/api/status").json()
        second_payload = client.get("/api/status").json()
        assert app.state.resources.db is owned_db

    assert payload["status"] == "ok"
    assert second_payload["status"] == "ok"
    assert payload["data_quality_gate"]["status"] == "warn"
    assert payload["data_quality_gate"]["reason_codes"] == ["KLINE_STALE_OR_LOW_COVERAGE"]
    assert payload["data_quality_gate"]["recovery_plan"][0]["command"] == [
        "trade",
        "data",
        "kline",
        "sync",
    ]
    assert payload["data_status"]["quality_gate"]["components"]["kline"]["status"] == "warn"
    assert app.state.resources.lifecycle.value == "stopped"
