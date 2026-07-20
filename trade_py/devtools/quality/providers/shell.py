"""Shell syntax and ShellCheck provider."""

from __future__ import annotations

from pathlib import Path

from trade_py.devtools.quality.models import CheckStep
from trade_py.devtools.quality.providers.base import ProviderContext, batched_paths


class ShellProvider:
    name = "shell"

    def matches(self, path: str) -> bool:
        return Path(path).name == "trade" or path.endswith((".sh", ".bash"))

    def plan(self, files: tuple[str, ...], context: ProviderContext) -> tuple[CheckStep, ...]:
        steps = [
            CheckStep(
                check_id=f"shell.syntax.{index + 1:03d}",
                group=self.name,
                name=f"Bash syntax: {path}",
                argv=("bash", "-n", "--", path),
                files=(path,),
                remediation_code="shell.syntax",
                remediation="Fix the Bash syntax error without hiding the child exit code.",
                version_argv=("bash", "--version"),
            )
            for index, path in enumerate(files)
        ]
        batches = batched_paths(
            files,
            argv_prefix=("shellcheck", "--"),
            max_bytes=context.config.max_argv_bytes,
        )
        for index, batch in enumerate(batches):
            steps.append(
                CheckStep(
                    check_id="shell.shellcheck"
                    if len(batches) == 1
                    else f"shell.shellcheck.{index + 1:03d}",
                    group=self.name,
                    name="ShellCheck",
                    argv=("shellcheck", "--", *batch),
                    files=batch,
                    remediation_code="shell.shellcheck",
                    remediation=context.config.setup_hint("shellcheck"),
                    version_argv=("shellcheck", "--version"),
                )
            )
        return tuple(steps)
