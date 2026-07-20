"""Python syntax, Ruff, and BasedPyright provider."""

from __future__ import annotations

import sys

from trade_py.devtools.quality.models import CheckStep, GateMode
from trade_py.devtools.quality.providers.base import ProviderContext, batch_id, batched_paths


class PythonProvider:
    name = "python"
    _suffixes = (".py", ".pyi")

    def matches(self, path: str) -> bool:
        return path.endswith(self._suffixes)

    def plan(self, files: tuple[str, ...], context: ProviderContext) -> tuple[CheckStep, ...]:
        steps: list[CheckStep] = []
        batches = batched_paths(
            files,
            argv_prefix=("ruff", "format", "--check", "--"),
            max_bytes=context.config.max_argv_bytes,
        )
        total = len(batches)
        for index, batch in enumerate(batches):
            format_id = batch_id("python.ruff_format", index, total)
            lint_id = batch_id("python.ruff_lint", index, total)
            syntax_id = batch_id("python.syntax", index, total)
            type_id = batch_id("python.basedpyright", index, total)
            if context.mode is GateMode.FIX:
                steps.append(
                    CheckStep(
                        check_id=format_id,
                        group=self.name,
                        name="Ruff format",
                        argv=("ruff", "format", "--", *batch),
                        files=batch,
                        mutates_source=True,
                        remediation_code="python.ruff_format",
                        remediation=context.config.setup_hint("ruff"),
                        version_argv=("ruff", "--version"),
                    )
                )
                steps.append(
                    CheckStep(
                        check_id=lint_id,
                        group=self.name,
                        name="Ruff lint fix",
                        argv=("ruff", "check", "--fix", "--", *batch),
                        files=batch,
                        prerequisites=(format_id,),
                        mutates_source=True,
                        remediation_code="python.ruff_lint",
                        remediation=context.config.setup_hint("ruff"),
                        version_argv=("ruff", "--version"),
                    )
                )
                check_prerequisites = (lint_id,)
            else:
                steps.extend(
                    (
                        CheckStep(
                            check_id=format_id,
                            group=self.name,
                            name="Ruff format check",
                            argv=("ruff", "format", "--check", "--", *batch),
                            files=batch,
                            remediation_code="python.ruff_format",
                            remediation="Run ./trade dev fix for the selected Python files.",
                            version_argv=("ruff", "--version"),
                        ),
                        CheckStep(
                            check_id=lint_id,
                            group=self.name,
                            name="Ruff lint",
                            argv=("ruff", "check", "--", *batch),
                            files=batch,
                            remediation_code="python.ruff_lint",
                            remediation="Fix the reported Ruff rule without a blanket suppression.",
                            version_argv=("ruff", "--version"),
                        ),
                    )
                )
                check_prerequisites = ()
            steps.extend(
                (
                    CheckStep(
                        check_id=syntax_id,
                        group=self.name,
                        name="Python syntax",
                        argv=(
                            sys.executable,
                            "-m",
                            "trade_py.devtools.quality.internal",
                            "python-syntax",
                            "--",
                            *batch,
                        ),
                        files=batch,
                        prerequisites=check_prerequisites,
                        remediation_code="python.syntax",
                        remediation="Fix the syntax error shown for the selected file.",
                        version_argv=(sys.executable, "--version"),
                    ),
                    CheckStep(
                        check_id=type_id,
                        group=self.name,
                        name="BasedPyright",
                        argv=(
                            "basedpyright",
                            "--project",
                            "pyproject.toml",
                            *(f"./{path}" for path in batch),
                        ),
                        files=batch,
                        prerequisites=check_prerequisites,
                        timeout_seconds=300,
                        remediation_code="python.types",
                        remediation="Fix changed-boundary type errors without disabling project checks.",
                        version_argv=("basedpyright", "--version"),
                    ),
                )
            )
        return tuple(steps)
