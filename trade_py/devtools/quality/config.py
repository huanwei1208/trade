"""Versioned ownership and tool-policy configuration."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from trade_py.devtools.quality.toml_compat import tomllib

DEFAULT_EXCLUDES = (
    ".git/**",
    ".venv/**",
    "**/__pycache__/**",
    "build/**",
    "dist/**",
    "**/target/**",
    "trade_web/frontend/node_modules/**",
    "trade_web/frontend/dist/**",
    "engine/vendor/**",
    "**/generated/**",
    "**/*.generated.*",
)
DEFAULT_PROTECTED = (
    "data/**",
    "models/**",
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    "**/*.parquet",
)
DEFAULT_SOURCE_EXTENSIONS = (
    ".py",
    ".pyi",
    ".sh",
    ".bash",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".java",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".rs",
    ".go",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".kts",
    ".scala",
)


@dataclass(frozen=True)
class QualityConfig:
    version: int = 1
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES
    protected: tuple[str, ...] = DEFAULT_PROTECTED
    fixtures: tuple[str, ...] = ("tests/fixtures/**", "**/src/test/resources/**")
    source_extensions: tuple[str, ...] = DEFAULT_SOURCE_EXTENSIONS
    max_argv_bytes: int = 65_536
    max_light_workers: int = 4
    max_git_processes: int = 10
    max_scope_discovery_ms: int = 2_000
    setup_hints: tuple[tuple[str, str], ...] = (
        ("ruff", "./trade setup-python"),
        ("basedpyright", "./trade setup-python"),
        ("shellcheck", "sudo apt-get install shellcheck"),
        ("clang-format", "sudo apt-get install clang-format"),
        (
            "mvn",
            "cd engine/tradedb-driver && mvn spotless:check test",
        ),
        ("npm", "npm --prefix trade_web/frontend ci"),
    )

    def setup_hint(self, executable: str) -> str:
        name = Path(executable).name
        for tool, hint in self.setup_hints:
            if name == tool or name.startswith(f"{tool}-"):
                return hint
        if "node_modules/.bin/" in executable:
            return "npm --prefix trade_web/frontend ci"
        return f"Install the pinned {name} tool explicitly."


def _strings(section: dict[str, Any], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = section.get(key)
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"quality.toml: {key} must be an array of strings")
    return tuple(value)


def load_config(repo_root: Path) -> QualityConfig:
    path = repo_root / "quality.toml"
    if not path.exists():
        return QualityConfig()

    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    version = raw.get("version", 1)
    if version != 1:
        raise ValueError(f"Unsupported quality.toml version: {version!r}")
    ownership = raw.get("ownership", {})
    execution = raw.get("execution", {})
    performance = raw.get("performance", {})
    tools = raw.get("setup", {})
    if (
        not isinstance(ownership, dict)
        or not isinstance(execution, dict)
        or not isinstance(performance, dict)
        or not isinstance(tools, dict)
    ):
        raise ValueError("quality.toml sections must be tables")
    hints = tuple((str(key), str(value)) for key, value in sorted(tools.items()))
    return QualityConfig(
        version=version,
        excludes=_strings(ownership, "exclude", DEFAULT_EXCLUDES),
        protected=_strings(ownership, "protected", DEFAULT_PROTECTED),
        fixtures=_strings(ownership, "fixtures", ("tests/fixtures/**", "**/src/test/resources/**")),
        source_extensions=_strings(ownership, "source_extensions", DEFAULT_SOURCE_EXTENSIONS),
        max_argv_bytes=int(execution.get("max_argv_bytes", 65_536)),
        max_light_workers=int(execution.get("max_light_workers", 4)),
        max_git_processes=int(performance.get("max_git_processes", 10)),
        max_scope_discovery_ms=int(performance.get("max_scope_discovery_ms", 2_000)),
        setup_hints=hints or QualityConfig().setup_hints,
    )


def matching_pattern(path: str, patterns: tuple[str, ...]) -> str | None:
    normalized = path.replace("\\", "/")
    for pattern in patterns:
        bare_prefix = pattern.removesuffix("/**")
        if normalized == bare_prefix or fnmatchcase(normalized, pattern):
            return pattern
    return None


def exclusion_reason(path: str, config: QualityConfig) -> str | None:
    if pattern := matching_pattern(path, config.protected):
        return f"protected:{pattern}"
    if pattern := matching_pattern(path, config.excludes):
        return f"excluded:{pattern}"
    return None


def is_source_like(path: str, config: QualityConfig) -> bool:
    return Path(path).suffix.lower() in config.source_extensions or Path(path).name == "trade"
