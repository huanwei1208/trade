"""Aggregate strict design checks without stealing ordinary file ownership."""

from __future__ import annotations

import re
import sys

from trade_py.devtools.design_quality.governance import resolve_governance_requirements
from trade_py.devtools.quality.models import (
    CheckStep,
    FailureKind,
    GateMode,
    ResourceClass,
    ScopeSelection,
)
from trade_py.devtools.quality.providers.base import ProviderContext

_CHANGE_RE = re.compile(r"^openspec/changes/(?P<change>[a-z0-9][a-z0-9-]*)/.+$")
_POLICY_RE = re.compile(r"^design-policy/v[1-9][0-9]*\.toml$")


class DesignQualityContributor:
    name = "design"

    def plan(self, selection: ScopeSelection, context: ProviderContext) -> tuple[CheckStep, ...]:
        if context.mode is not GateMode.CHECK:
            return ()
        changed = set(selection.files) | set(selection.deleted_files)
        matched = {path: match for path in changed if (match := _CHANGE_RE.fullmatch(path))}
        policy_paths = sorted(path for path in changed if _POLICY_RE.fullmatch(path))
        if not matched and not policy_paths:
            return ()

        changes = sorted({match.group("change") for match in matched.values()})
        resolution = resolve_governance_requirements(
            context.repo_root,
            changes,
            new_change_names=selection.new_change_names,
            deleted_files=selection.deleted_files,
        )
        added = set(selection.added_files)
        deleted = set(selection.deleted_files)
        delta = set(selection.delta_files)

        argv = [
            sys.executable,
            "-m",
            "trade_py.devtools.design_quality.cli",
            "--strict",
        ]
        for change in resolution.live_changes:
            argv.extend(("--change", change))
        for change in resolution.required_changes:
            if change in resolution.live_changes:
                argv.extend(("--require-governance", change))
        for change in resolution.missing_required_changes:
            argv.extend(("--missing-required", change))
        for path in policy_paths:
            if path in delta and (path in deleted or path not in added):
                argv.extend(("--immutable-policy-edit", path))
        return (
            CheckStep(
                check_id="design.strict",
                group=self.name,
                name="Governed OpenSpec design approval",
                argv=tuple(argv),
                files=tuple(sorted(set(matched) | set(policy_paths))),
                timeout_seconds=30,
                output_limit_bytes=16_777_216,
                resource_class=ResourceClass.HEAVY,
                remediation_code="design.strict",
                remediation=(
                    "Run ./trade dev design-check <change>, resolve findings, complete the "
                    "six-role review, then rerun with --strict."
                ),
                exit_code_kinds=(
                    (1, FailureKind.QUALITY),
                    (2, FailureKind.INFRASTRUCTURE),
                ),
                nonzero_kind=FailureKind.INFRASTRUCTURE,
                structured_output_schema="trade.design.batch.v1",
            ),
        )
