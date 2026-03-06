from __future__ import annotations

from trade_py.db.settings_db import SettingsDB


class AccountRepository:
    """Persistence adapter for account/watchlist settings."""

    def __init__(self, data_root: str) -> None:
        self._db = SettingsDB(data_root)

    def watch_add(self, symbol: str, note: str = "") -> None:
        self._db.watchlist_add(symbol, note)

    def watch_remove(self, symbol: str) -> None:
        self._db.watchlist_remove(symbol)

    def watch_list(self) -> list[str]:
        return self._db.watchlist_get()

    def watch_list_with_names(self) -> list[dict]:
        return self._db.watchlist_get_with_names()

    def watch_lookup(self, symbol: str) -> dict | None:
        return self._db.instrument_lookup(symbol)

    def setting_set(self, key: str, value: str) -> None:
        self._db.set(key, value)

    def setting_get(self, key: str):
        return self._db.get(key)
