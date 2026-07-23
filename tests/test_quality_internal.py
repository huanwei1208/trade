from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_py.devtools.quality import internal


def test_blanket_suppression_fails_but_scoped_suppression_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.py"
    good = tmp_path / "good.py"
    bad.write_text("value = dynamic  # type: ignore\n", encoding="utf-8")
    good.write_text(
        "value = dynamic  # type: ignore[assignment] -- upstream stub mismatch\n",
        encoding="utf-8",
    )

    assert internal.main(["suppression-audit", "--", str(bad)]) == 1
    assert internal.main(["suppression-audit", "--", str(good)]) == 0


def test_dependency_lock_consistency_detects_stale_frontend_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    frontend = tmp_path / "trade_web" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text(
        json.dumps({"devDependencies": {"eslint": "^9.0.0"}}),
        encoding="utf-8",
    )
    (frontend / "package-lock.json").write_text(
        json.dumps({"packages": {"": {"devDependencies": {}}}}),
        encoding="utf-8",
    )

    assert internal.main(["lock-consistency"]) == 1

    (frontend / "package-lock.json").write_text(
        json.dumps({"packages": {"": {"devDependencies": {"eslint": "^9.0.0"}}}}),
        encoding="utf-8",
    )
    assert internal.main(["lock-consistency"]) == 0
