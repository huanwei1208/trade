"""Offline Maven and Spotless provider for the JDBC module."""

from __future__ import annotations

from trade_py.devtools.quality.models import CheckStep, GateMode, ResourceClass
from trade_py.devtools.quality.providers.base import ProviderContext


class JavaProvider:
    name = "java"
    _module = "engine/tradedb-driver"

    def matches(self, path: str) -> bool:
        return path == f"{self._module}/pom.xml" or (
            path.startswith(f"{self._module}/") and path.endswith(".java")
        )

    def plan(self, files: tuple[str, ...], context: ProviderContext) -> tuple[CheckStep, ...]:
        relative_java = tuple(
            path.removeprefix(f"{self._module}/") for path in files if path.endswith(".java")
        )
        if context.mode is GateMode.FIX and relative_java:
            filter_arg = f"-DspotlessFiles={','.join(relative_java)}"
            format_argv = ("mvn", "-o", "-q", filter_arg, "spotless:apply")
            format_name = "Maven Spotless fix"
        else:
            format_argv = ("mvn", "-o", "-q", "spotless:check")
            format_name = "Maven Spotless check"
        steps: list[CheckStep] = [
            CheckStep(
                check_id="java.spotless",
                group=self.name,
                name=format_name,
                argv=format_argv,
                cwd=self._module,
                files=files,
                mutates_source=context.mode is GateMode.FIX and bool(relative_java),
                timeout_seconds=300,
                resource_class=ResourceClass.HEAVY,
                remediation_code="java.spotless",
                remediation=context.config.setup_hint("mvn"),
                version_argv=("mvn", "--version"),
            )
        ]
        if context.all_mode:
            steps.append(
                CheckStep(
                    check_id="java.tests",
                    group=self.name,
                    name="Maven tests",
                    argv=("mvn", "-o", "-q", "test"),
                    cwd=self._module,
                    files=files,
                    prerequisites=("java.spotless",),
                    timeout_seconds=900,
                    output_limit_bytes=131_072,
                    resource_class=ResourceClass.HEAVY,
                    permitted_outputs=(f"{self._module}/target/**",),
                    remediation_code="java.tests",
                    remediation="Fix the focused JDBC test failure; do not enable networked Maven resolution.",
                    version_argv=("mvn", "--version"),
                )
            )
        return tuple(steps)
