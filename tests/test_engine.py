from __future__ import annotations

import sys
import types

from trade_py.engine import ingest_articles


def test_ingest_articles_uses_sentiment_cli_range_args(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    fake_db_module = types.ModuleType("trade_py.db.trade_db")

    class FakeTradeDB:
        def __init__(self, data_root: str) -> None:
            captured["data_root"] = data_root

        def get(self, key: str, default=None):
            return default

    fake_db_module.TradeDB = FakeTradeDB
    monkeypatch.setitem(sys.modules, "trade_py.db.trade_db", fake_db_module)

    fake_sentiment_module = types.ModuleType("trade_py.cli._sentiment")

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = list(argv)
        return 0

    fake_sentiment_module.main = fake_main
    monkeypatch.setitem(sys.modules, "trade_py.cli._sentiment", fake_sentiment_module)

    result = ingest_articles(
        "rss",
        str(tmp_path),
        fetch_mode="range",
        semantic_mode="base",
        date_from="2026-03-19",
        date_to="2026-03-20",
    )

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "--source" in argv and argv[argv.index("--source") + 1] == "rss"
    assert "--start" in argv and argv[argv.index("--start") + 1] == "2026-03-19"
    assert "--end" in argv and argv[argv.index("--end") + 1] == "2026-03-20"
    assert "--date-from" not in argv
    assert "--date-to" not in argv
    assert result["summary"].startswith("情绪抓取完成:")

