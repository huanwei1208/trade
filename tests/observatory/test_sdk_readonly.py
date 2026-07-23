"""WP2.6 read-only SDK tests: zero-network, zero-write, composite-not-dataset."""
from __future__ import annotations

import pytest

from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode
from trade_py.observatory.query.sdk import observe
from tests.observatory.fixtures import build_observatory_fixture


@pytest.fixture()
def data_root(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    return fx["data_root"]


def test_sdk_snapshot_bars(data_root):
    ctx = observe("crypto.BTC", data_root).snapshot(channel="formal")
    bars = ctx.bars()
    assert bars
    assert all("close" in row for row in bars)
    assert ctx.snapshot_id


def test_sdk_findings_and_context(data_root):
    handle = observe("crypto.BTC", data_root).snapshot(channel="evaluated_candidate")
    findings = handle.findings()
    assert "count" in findings
    assert handle.context.resolved_channel == "evaluated_candidate"


def test_sdk_composite_cannot_be_dataset(data_root):
    comp = observe("crypto.BTC", data_root).composite()
    with pytest.raises(ObservatoryError) as exc:
        comp.bars()
    assert exc.value.reason_code == ReasonCode.COMPOSITE_NOT_DATASET


def test_sdk_unsupported_asset(data_root):
    with pytest.raises(ObservatoryError) as exc:
        observe("crypto.ETH", data_root)
    assert exc.value.reason_code == ReasonCode.SNAPSHOT_NOT_FOUND


def test_sdk_read_does_not_write_or_network(data_root, monkeypatch):
    # Any network attempt must raise; the read path must not touch the network.
    import socket

    def _no_network(*args, **kwargs):  # pragma: no cover - only triggers on violation
        raise AssertionError("read path attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _no_network)

    # Snapshot fingerprint of the data tree before/after must be unchanged.
    import hashlib

    def tree_hash(root):
        h = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if path.is_file() and "observatory" not in str(path):
                h.update(str(path).encode())
                h.update(path.read_bytes())
        return h.hexdigest()

    crypto_root = data_root / "market" / "crypto"
    before = tree_hash(crypto_root)
    handle = observe("crypto.BTC", data_root).snapshot(channel="formal")
    handle.bars()
    handle.findings()
    observe("crypto.BTC", data_root).composite()
    after = tree_hash(crypto_root)
    assert before == after
