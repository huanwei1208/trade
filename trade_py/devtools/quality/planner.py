"""Turn an owned file scope into language-specific typed steps."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from trade_py.devtools.quality.config import QualityConfig, exclusion_reason, is_source_like
from trade_py.devtools.quality.models import (
    CheckStep,
    Exclusion,
    GateMode,
    GatePlan,
    PlanIssue,
    ScopeSelection,
)
from trade_py.devtools.quality.providers import ProviderRegistry
from trade_py.devtools.quality.providers.base import ProviderContext, batched_paths


def build_plan(
    selection: ScopeSelection,
    *,
    mode: GateMode,
    config: QualityConfig,
    registry: ProviderRegistry | None = None,
) -> GatePlan:
    providers = registry or ProviderRegistry()
    groups: dict[str, list[str]] = defaultdict(list)
    exclusions: list[Exclusion] = []
    issues: list[PlanIssue] = []
    eligible: list[str] = []

    for path in selection.files:
        if reason := exclusion_reason(path, config):
            exclusions.append(Exclusion(path=path, reason=reason))
            continue
        owner = providers.owner_for(path)
        if owner is None:
            if is_source_like(path, config):
                issues.append(
                    PlanIssue(
                        code="scope.uncovered_source",
                        message=f"No quality provider owns first-party source: {path}",
                        files=(path,),
                    )
                )
            else:
                exclusions.append(Exclusion(path=path, reason="unsupported-non-source"))
            continue
        eligible.append(path)
        groups[owner.name].append(path)

    context = ProviderContext(
        repo_root=Path(selection.repo_root),
        config=config,
        mode=mode,
        all_mode=selection.all_mode,
    )
    steps: list[CheckStep] = []
    for provider in providers.providers:
        files = tuple(sorted(groups.get(provider.name, ())))
        if files:
            steps.extend(provider.plan(files, context))

    mutation_ids = tuple(step.check_id for step in steps if step.mutates_source)
    eligible_tuple = tuple(sorted(eligible))
    if eligible_tuple:
        batches = batched_paths(
            eligible_tuple,
            argv_prefix=(
                sys.executable,
                "-m",
                "trade_py.devtools.quality.internal",
                "text-hygiene",
                "--",
            ),
            max_bytes=config.max_argv_bytes,
        )
        for index, batch in enumerate(batches):
            steps.append(
                CheckStep(
                    check_id="shared.text_hygiene"
                    if len(batches) == 1
                    else f"shared.text_hygiene.{index + 1:03d}",
                    group="shared",
                    name="Owned text hygiene",
                    argv=(
                        sys.executable,
                        "-m",
                        "trade_py.devtools.quality.internal",
                        "text-hygiene",
                        "--",
                        *batch,
                    ),
                    files=batch,
                    prerequisites=mutation_ids,
                    remediation_code="shared.text_hygiene",
                    remediation="Remove trailing whitespace/NUL bytes and add the final newline.",
                    version_argv=(sys.executable, "--version"),
                )
            )

        audit_files = tuple(
            path
            for path in eligible_tuple
            if Path(path).suffix.lower()
            in {
                ".c",
                ".cc",
                ".cpp",
                ".cxx",
                ".h",
                ".hh",
                ".hpp",
                ".hxx",
                ".js",
                ".jsx",
                ".py",
                ".pyi",
                ".toml",
                ".ts",
                ".tsx",
            }
        )
        audit_batches = batched_paths(
            audit_files,
            argv_prefix=(
                sys.executable,
                "-m",
                "trade_py.devtools.quality.internal",
                "suppression-audit",
                "--",
            ),
            max_bytes=config.max_argv_bytes,
        )
        for index, batch in enumerate(audit_batches):
            steps.append(
                CheckStep(
                    check_id="shared.suppression_audit"
                    if len(audit_batches) == 1
                    else f"shared.suppression_audit.{index + 1:03d}",
                    group="shared",
                    name="Blanket suppression audit",
                    argv=(
                        sys.executable,
                        "-m",
                        "trade_py.devtools.quality.internal",
                        "suppression-audit",
                        "--",
                        *batch,
                    ),
                    files=batch,
                    prerequisites=mutation_ids,
                    remediation_code="shared.suppressions",
                    remediation="Use the narrowest rule and scope with reason, owner, and expiry.",
                    version_argv=(sys.executable, "--version"),
                )
            )

        lock_files = {
            "pyproject.toml",
            "uv.lock",
            "trade_web/frontend/package.json",
            "trade_web/frontend/package-lock.json",
        }
        if selected_locks := lock_files.intersection(eligible_tuple):
            steps.append(
                CheckStep(
                    check_id="shared.lock_consistency",
                    group="shared",
                    name="Dependency lock consistency",
                    argv=(
                        sys.executable,
                        "-m",
                        "trade_py.devtools.quality.internal",
                        "lock-consistency",
                    ),
                    files=tuple(sorted(selected_locks)),
                    prerequisites=mutation_ids,
                    remediation_code="shared.locks",
                    remediation="Regenerate uv.lock or package-lock.json with the owning package manager.",
                    version_argv=(sys.executable, "--version"),
                )
            )

    step_ids = [step.check_id for step in steps]
    duplicates = sorted({item for item in step_ids if step_ids.count(item) > 1})
    if duplicates:
        issues.append(
            PlanIssue(
                code="plan.duplicate_check_id",
                message=f"Duplicate stable check IDs: {', '.join(duplicates)}",
            )
        )
    known_ids = set(step_ids)
    for step in steps:
        missing = tuple(item for item in step.prerequisites if item not in known_ids)
        if missing:
            issues.append(
                PlanIssue(
                    code="plan.missing_prerequisite",
                    message=f"{step.check_id} has missing prerequisites: {', '.join(missing)}",
                )
            )

    ordered_steps = tuple(sorted(steps, key=lambda item: item.check_id))
    if mode is GateMode.CHECK:
        illegal = tuple(step.check_id for step in ordered_steps if step.mutates_source)
        write_tokens = {"--fix", "--write", "-i", "spotless:apply"}
        illegal_argv = tuple(
            step.check_id
            for step in ordered_steps
            if any(token in write_tokens for token in step.argv)
        )
        if illegal:
            issues.append(
                PlanIssue(
                    code="plan.check_mutation",
                    message=f"Check plan contains source mutations: {', '.join(illegal)}",
                )
            )
        if illegal_argv:
            issues.append(
                PlanIssue(
                    code="plan.check_write_argv",
                    message=f"Check plan contains formatter write flags: {', '.join(illegal_argv)}",
                )
            )
    else:
        # Defensive assertion: a provider may only mutate files already classified as owned.
        owned = set(eligible_tuple)
        for step in ordered_steps:
            if step.mutates_source and not set(step.files).issubset(owned):
                issues.append(
                    PlanIssue(
                        code="plan.unowned_mutation",
                        message=f"{step.check_id} targets an unowned file",
                        files=tuple(sorted(set(step.files) - owned)),
                    )
                )

    return GatePlan(
        mode=mode,
        selection=selection,
        steps=ordered_steps,
        eligible_files=eligible_tuple,
        exclusions=tuple(sorted(exclusions, key=lambda item: item.path)),
        issues=tuple(issues),
    )
