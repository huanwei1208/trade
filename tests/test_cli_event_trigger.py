from __future__ import annotations

from pathlib import Path

import pytest

from trade_py.cli import event


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{", "Invalid --payload JSON"),
        ("[]", "expected a JSON object, got list"),
        ("0", "expected a JSON object, got int"),
        ("null", "expected a JSON object, got NoneType"),
    ],
)
def test_trigger_rejects_invalid_or_non_object_payload_before_database_creation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: str,
    message: str,
) -> None:
    exit_code = event.main(
        [
            "trigger",
            "ops.fixture",
            "--data-root",
            str(tmp_path),
            "--payload",
            payload,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert message in captured.err
    assert captured.out == ""
    assert not (tmp_path / ".db" / "trade.db").exists()
