"""Protocol for checks that observe a complete scope without owning files."""

from __future__ import annotations

from typing import Protocol

from trade_py.devtools.quality.models import CheckStep, ScopeSelection
from trade_py.devtools.quality.providers.base import ProviderContext


class ScopeContributor(Protocol):
    name: str

    def plan(
        self, selection: ScopeSelection, context: ProviderContext
    ) -> tuple[CheckStep, ...]: ...
