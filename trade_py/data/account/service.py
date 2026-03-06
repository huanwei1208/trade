from __future__ import annotations

from trade_py.data.account.repository import AccountRepository


class AccountService:
    """Domain service for account/watchlist operations."""

    def __init__(self, repository: AccountRepository) -> None:
        self._repo = repository

    def add_watch(self, symbol: str, note: str = "") -> None:
        self._repo.watch_add(symbol.strip().upper(), note)

    def remove_watch(self, symbol: str) -> None:
        self._repo.watch_remove(symbol.strip().upper())

    def list_watch(self) -> list[str]:
        return self._repo.watch_list()

    def set_setting(self, key: str, value: str) -> None:
        self._repo.setting_set(key, value)

    def get_setting(self, key: str):
        return self._repo.setting_get(key)
