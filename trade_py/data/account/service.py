from __future__ import annotations

from trade_py.data.account.repository import AccountRepository
from trade_py.data.market.kline.providers import ensure_symbol


def _normalize(symbol: str) -> str:
    return ensure_symbol(symbol.strip())


class AccountService:
    """Domain service for account/watchlist operations."""

    def __init__(self, repository: AccountRepository) -> None:
        self._repo = repository

    def lookup_instrument(self, symbol: str) -> dict | None:
        """Return instrument info dict or None if symbol not in instruments DB."""
        return self._repo.watch_lookup(_normalize(symbol))

    def add_watch(self, symbol: str, note: str = "") -> None:
        self._repo.watch_add(_normalize(symbol), note)

    def remove_watch(self, symbol: str) -> None:
        self._repo.watch_remove(_normalize(symbol))

    def list_watch(self) -> list[str]:
        return self._repo.watch_list()

    def list_watch_with_names(self) -> list[dict]:
        return self._repo.watch_list_with_names()

    def set_setting(self, key: str, value: str) -> None:
        self._repo.setting_set(key, value)

    def get_setting(self, key: str):
        return self._repo.setting_get(key)
