"""Run the read-only package authority guard for relevant source changes."""

from __future__ import annotations

import sys

from trade_py.devtools.quality.models import CheckStep, FailureKind, GateMode, ScopeSelection
from trade_py.devtools.quality.providers.base import ProviderContext

_EXACT_TRIGGERS = frozenset({"layout-authority.toml", "pyproject.toml"})
_PREFIX_TRIGGERS = (
    "src/trade/",
    "trade_py/",
)


class LayoutAuthorityContributor:
    name = "layout"

    def plan(self, selection: ScopeSelection, context: ProviderContext) -> tuple[CheckStep, ...]:
        if context.mode is not GateMode.CHECK:
            return ()
        changed = set(selection.files) | set(selection.deleted_files)
        relevant = tuple(
            sorted(
                path
                for path in changed
                if path in _EXACT_TRIGGERS
                or (
                    path.endswith((".py", ".pyi"))
                    and any(path.startswith(prefix) for prefix in _PREFIX_TRIGGERS)
                )
            )
        )
        if not relevant:
            return ()
        candidates = tuple(
            sorted(path for path in selection.files if path.startswith(("src/trade/", "trade_py/")))
        )
        argv = [
            sys.executable,
            "-m",
            "trade_py.devtools.layout.cli",
            "--repo-root",
            ".",
        ]
        for path in candidates:
            argv.extend(("--candidate", path))
        return (
            CheckStep(
                check_id="layout.authority",
                group=self.name,
                name="Package module authority",
                argv=tuple(argv),
                files=relevant,
                timeout_seconds=30,
                output_limit_bytes=1_048_576,
                remediation_code="layout.authority",
                remediation=(
                    "Add or correct the strict-approved immutable authority record; "
                    "do not bypass the guard with aliases, path extension, or exclusions."
                ),
                exit_code_kinds=(
                    (1, FailureKind.QUALITY),
                    (2, FailureKind.INFRASTRUCTURE),
                ),
                nonzero_kind=FailureKind.INFRASTRUCTURE,
                structured_output_schema="trade.layout.authority-report.v1",
                version_argv=(sys.executable, "--version"),
            ),
        )
