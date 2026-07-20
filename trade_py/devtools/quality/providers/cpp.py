"""Owned C/C++ formatting plus full CMake validation provider."""

from __future__ import annotations

from trade_py.devtools.quality.models import CheckStep, GateMode, ResourceClass
from trade_py.devtools.quality.providers.base import ProviderContext, batch_id, batched_paths


class CppProvider:
    name = "cpp"
    _suffixes = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")

    def matches(self, path: str) -> bool:
        return path.endswith(self._suffixes)

    def plan(self, files: tuple[str, ...], context: ProviderContext) -> tuple[CheckStep, ...]:
        prefix = (
            ("clang-format", "-i", "--")
            if context.mode is GateMode.FIX
            else ("clang-format", "--dry-run", "--Werror", "--")
        )
        batches = batched_paths(files, argv_prefix=prefix, max_bytes=context.config.max_argv_bytes)
        steps: list[CheckStep] = []
        for index, batch in enumerate(batches):
            steps.append(
                CheckStep(
                    check_id=batch_id("cpp.clang_format", index, len(batches)),
                    group=self.name,
                    name="clang-format" if context.mode is GateMode.FIX else "clang-format check",
                    argv=(*prefix, *batch),
                    files=batch,
                    mutates_source=context.mode is GateMode.FIX,
                    remediation_code="cpp.format",
                    remediation=context.config.setup_hint("clang-format"),
                    version_argv=("clang-format", "--version"),
                )
            )
        if context.all_mode:
            steps.extend(
                (
                    CheckStep(
                        check_id="cpp.cmake_configure",
                        group=self.name,
                        name="CMake configure",
                        argv=("./trade", "configure", "linux-clang"),
                        timeout_seconds=300,
                        resource_class=ResourceClass.HEAVY,
                        permitted_outputs=("build/linux-clang/**",),
                        remediation_code="cpp.configure",
                        remediation="Inspect the CMake configure diagnostic.",
                    ),
                    CheckStep(
                        check_id="cpp.cmake_build",
                        group=self.name,
                        name="CMake build",
                        argv=("./trade", "build", "linux-clang"),
                        prerequisites=("cpp.cmake_configure",),
                        timeout_seconds=1_800,
                        output_limit_bytes=131_072,
                        resource_class=ResourceClass.HEAVY,
                        permitted_outputs=("build/linux-clang/**",),
                        remediation_code="cpp.build",
                        remediation="Fix the first owned-source compiler error.",
                    ),
                    CheckStep(
                        check_id="cpp.ctest",
                        group=self.name,
                        name="C++ ctest",
                        argv=("./trade", "test", "linux-clang"),
                        prerequisites=("cpp.cmake_build",),
                        timeout_seconds=1_800,
                        output_limit_bytes=131_072,
                        resource_class=ResourceClass.HEAVY,
                        permitted_outputs=("build/linux-clang/**",),
                        remediation_code="cpp.test",
                        remediation="Fix the failing ctest before completion.",
                    ),
                )
            )
        return tuple(steps)
