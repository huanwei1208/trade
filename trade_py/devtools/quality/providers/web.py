"""Prettier, ESLint, TypeScript, and frontend build provider."""

from __future__ import annotations

from pathlib import Path

from trade_py.devtools.quality.models import CheckStep, GateMode, ResourceClass
from trade_py.devtools.quality.providers.base import ProviderContext, batch_id, batched_paths


class WebProvider:
    name = "web"
    _root = "trade_web/frontend"
    _code_suffixes = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
    _format_suffixes = (*_code_suffixes, ".json", ".jsonc", ".css", ".html")
    _names = {"package.json", "package-lock.json", ".prettierrc.json"}

    def matches(self, path: str) -> bool:
        item = Path(path)
        return path.startswith(f"{self._root}/") and (
            path.endswith(self._format_suffixes) or item.name in self._names
        )

    def plan(self, files: tuple[str, ...], context: ProviderContext) -> tuple[CheckStep, ...]:
        relative = tuple(path.removeprefix(f"{self._root}/") for path in files)
        format_files = tuple(path for path in relative if Path(path).name != "package-lock.json")
        lint_files = tuple(path for path in relative if path.endswith(self._code_suffixes))
        prettier = "node_modules/.bin/prettier"
        eslint = "node_modules/.bin/eslint"
        prettier_action = "--write" if context.mode is GateMode.FIX else "--check"
        prettier_prefix = (prettier, prettier_action, "--")
        prettier_batches = batched_paths(
            format_files,
            argv_prefix=prettier_prefix,
            max_bytes=context.config.max_argv_bytes,
        )
        steps: list[CheckStep] = []
        formatter_ids: list[str] = []
        for index, batch in enumerate(prettier_batches):
            check_id = batch_id("web.prettier", index, len(prettier_batches))
            formatter_ids.append(check_id)
            steps.append(
                CheckStep(
                    check_id=check_id,
                    group=self.name,
                    name="Prettier fix" if context.mode is GateMode.FIX else "Prettier check",
                    argv=(*prettier_prefix, *batch),
                    cwd=self._root,
                    files=tuple(f"{self._root}/{path}" for path in batch),
                    mutates_source=context.mode is GateMode.FIX,
                    remediation_code="web.prettier",
                    remediation=context.config.setup_hint(prettier),
                    version_argv=(prettier, "--version"),
                )
            )

        eslint_action = ("--fix",) if context.mode is GateMode.FIX else ()
        eslint_prefix = (eslint, *eslint_action, "--")
        eslint_batches = batched_paths(
            lint_files,
            argv_prefix=eslint_prefix,
            max_bytes=context.config.max_argv_bytes,
        )
        linter_ids: list[str] = []
        for index, batch in enumerate(eslint_batches):
            check_id = batch_id("web.eslint", index, len(eslint_batches))
            linter_ids.append(check_id)
            steps.append(
                CheckStep(
                    check_id=check_id,
                    group=self.name,
                    name="ESLint fix" if context.mode is GateMode.FIX else "ESLint",
                    argv=(*eslint_prefix, *batch),
                    cwd=self._root,
                    files=tuple(f"{self._root}/{path}" for path in batch),
                    prerequisites=tuple(formatter_ids) if context.mode is GateMode.FIX else (),
                    mutates_source=context.mode is GateMode.FIX,
                    remediation_code="web.eslint",
                    remediation=context.config.setup_hint(eslint),
                    version_argv=(eslint, "--version"),
                )
            )

        fix_prerequisites = (
            tuple(linter_ids or formatter_ids) if context.mode is GateMode.FIX else ()
        )
        steps.append(
            CheckStep(
                check_id="web.typescript",
                group=self.name,
                name="TypeScript typecheck",
                argv=("npm", "run", "typecheck"),
                cwd=self._root,
                files=files,
                prerequisites=fix_prerequisites,
                timeout_seconds=600,
                permitted_outputs=(f"{self._root}/*.tsbuildinfo",),
                remediation_code="web.types",
                remediation=context.config.setup_hint("npm"),
                version_argv=("npm", "--version"),
            )
        )
        if context.all_mode:
            steps.append(
                CheckStep(
                    check_id="web.build",
                    group=self.name,
                    name="Frontend production build",
                    argv=("npm", "run", "build"),
                    cwd=self._root,
                    files=files,
                    prerequisites=("web.typescript",),
                    timeout_seconds=900,
                    output_limit_bytes=131_072,
                    resource_class=ResourceClass.HEAVY,
                    permitted_outputs=(f"{self._root}/dist/**", f"{self._root}/*.tsbuildinfo"),
                    remediation_code="web.build",
                    remediation="Fix the production build failure without weakening strict TypeScript.",
                    version_argv=("npm", "--version"),
                )
            )
        return tuple(steps)
