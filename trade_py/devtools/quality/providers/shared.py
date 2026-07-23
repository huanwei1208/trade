"""Repository text hygiene and configuration parsing provider."""

from __future__ import annotations

import sys
from pathlib import Path

from trade_py.devtools.quality.models import CheckStep
from trade_py.devtools.quality.providers.base import ProviderContext, batched_paths


class SharedProvider:
    name = "shared"
    _suffixes = (
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".md",
        ".rst",
        ".txt",
        ".cmake",
        ".xml",
        ".lock",
    )
    _names = {
        "CMakeLists.txt",
        "Makefile",
        ".clang-format",
        ".editorconfig",
        ".gitignore",
        ".prettierignore",
    }

    def matches(self, path: str) -> bool:
        item = Path(path)
        return item.name in self._names or item.suffix.lower() in self._suffixes

    def plan(self, files: tuple[str, ...], context: ProviderContext) -> tuple[CheckStep, ...]:
        parseable = tuple(path for path in files if path.endswith((".json", ".toml")))
        if not parseable:
            return ()
        batches = batched_paths(
            parseable,
            argv_prefix=(
                sys.executable,
                "-m",
                "trade_py.devtools.quality.internal",
                "config-parse",
                "--",
            ),
            max_bytes=context.config.max_argv_bytes,
        )
        return tuple(
            CheckStep(
                check_id="shared.config_parse"
                if len(batches) == 1
                else f"shared.config_parse.{index + 1:03d}",
                group=self.name,
                name="JSON/TOML parse",
                argv=(
                    sys.executable,
                    "-m",
                    "trade_py.devtools.quality.internal",
                    "config-parse",
                    "--",
                    *batch,
                ),
                files=batch,
                remediation_code="shared.config_parse",
                remediation="Fix the malformed JSON/TOML configuration.",
                version_argv=(sys.executable, "--version"),
            )
            for index, batch in enumerate(batches)
        )
