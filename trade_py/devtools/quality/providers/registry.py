"""Ordered provider registry; the planner remains language-agnostic."""

from __future__ import annotations

from trade_py.devtools.quality.contributors import DesignQualityContributor
from trade_py.devtools.quality.contributors.base import ScopeContributor
from trade_py.devtools.quality.providers.base import QualityProvider
from trade_py.devtools.quality.providers.cpp import CppProvider
from trade_py.devtools.quality.providers.java import JavaProvider
from trade_py.devtools.quality.providers.python import PythonProvider
from trade_py.devtools.quality.providers.shared import SharedProvider
from trade_py.devtools.quality.providers.shell import ShellProvider
from trade_py.devtools.quality.providers.web import WebProvider


class ProviderRegistry:
    def __init__(
        self,
        providers: tuple[QualityProvider, ...] | None = None,
        contributors: tuple[ScopeContributor, ...] | None = None,
    ) -> None:
        self._providers = providers or (
            PythonProvider(),
            ShellProvider(),
            CppProvider(),
            JavaProvider(),
            WebProvider(),
            SharedProvider(),
        )
        self._contributors = (
            contributors if contributors is not None else (DesignQualityContributor(),)
        )

    @property
    def providers(self) -> tuple[QualityProvider, ...]:
        return self._providers

    @property
    def contributors(self) -> tuple[ScopeContributor, ...]:
        return self._contributors

    def owner_for(self, path: str) -> QualityProvider | None:
        return next((provider for provider in self._providers if provider.matches(path)), None)
