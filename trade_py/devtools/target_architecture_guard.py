"""Static dependency guard for the additive ``src/trade`` target packages.

The scanner reads Python source only. It never imports application modules, and
it remains dormant for historical fixture repositories that do not contain the
new Kernel package.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from trade_py.devtools.architecture_guard import ArchitectureFinding
from trade_py.devtools.target_import_analysis import (
    ImportAnalysis,
    ImportEdge,
    PythonSource,
    analyze_imports,
    is_stdlib,
    literal_all,
    literal_string,
    matches_any,
    module_name,
)

KERNEL_MODULE_ALLOWLIST = "target.kernel.module-allowlist"
KERNEL_DEPENDENCY = "target.kernel.dependency"
KERNEL_OWNER_VOCABULARY = "target.kernel.owner-vocabulary"
PLATFORM_DEPENDENCY = "target.platform.dependency"
PROCESSES_DEPENDENCY = "target.processes.dependency"
TARGET_LEGACY_DEPENDENCY = "target.package.legacy-dependency"
COMPAT_ADAPTER_BOUNDARY = "target.compat.adapter-boundary"
COMPAT_AGGREGATE_REEXPORT = "target.compat.aggregate-reexport"
RUNTIME_ADOPTION_FENCE = "target.runtime.adoption-fence"
DYNAMIC_IMPORT_UNRESOLVED = "target.dynamic-import.unresolved"
DYNAMIC_REEXPORT = "target.dynamic-reexport"
TARGET_SOURCE_UNAVAILABLE = "target.source.unavailable"

_KERNEL_MODULES = frozenset({"digest", "envelope", "errors", "ids", "result", "time"})
_KERNEL_FILES = frozenset({"__init__.py", *{f"{name}.py" for name in _KERNEL_MODULES}})
_KERNEL_PREFIXES = tuple(f"trade.kernel.{name}" for name in sorted(_KERNEL_MODULES))
_LEGACY_PREFIXES = ("trade_py", "trade_web")
_TARGET_PREFIXES = ("trade.kernel", "trade.platform", "trade.processes")
_COMPAT_MODULES = frozenset(
    {
        "trade_py.compat.bus_contracts",
        "trade_py.compat.job_run_contracts",
        "trade_py.compat.observatory_contracts",
        "trade_py.compat.runtime_contracts",
    }
)
_COMPAT_FILES = frozenset(
    {"__init__.py", *{name.rsplit(".", 1)[-1] + ".py" for name in _COMPAT_MODULES}}
)
_COMPAT_ALLOWED_PREFIXES = {
    "trade_py.compat.bus_contracts": (
        "trade.kernel",
        "trade.platform.contracts",
        "trade_py.bus",
    ),
    "trade_py.compat.job_run_contracts": (
        "trade.kernel",
        "trade.platform.contracts",
        "trade.processes.contracts",
        "trade_py.db.trade_db",
    ),
    "trade_py.compat.observatory_contracts": (
        "trade.kernel",
        "trade.platform.contracts",
        "trade_py.observatory.domain",
    ),
    "trade_py.compat.runtime_contracts": (
        "trade.kernel",
        "trade.platform.contracts",
        "trade_web.backend.runtime",
    ),
}
_KERNEL_OWNER_WORDS = frozenset(
    {
        "actor",
        "dataframe",
        "database",
        "dataset",
        "eventbus",
        "filesystem",
        "http",
        "native",
        "policy",
        "portfolio",
        "process",
        "provider",
        "recommendation",
        "runtime",
        "scheduler",
        "study",
    }
)
_WORD_TOKEN = re.compile(r"[A-Za-z][a-z]*|[A-Z]+(?![a-z])|[0-9]+")
_CLI_MODULES = frozenset(
    {
        "account",
        "backup",
        "config",
        "daily",
        "data",
        "dev",
        "doctor",
        "evaluate",
        "event",
        "factor",
        "inspect",
        "kg",
        "model",
        "observatory",
        "ops",
        "research",
        "run",
        "show",
        "start",
        "status",
        "web",
    }
)
_FINITE_GETATTR_EXPORTS = {
    "trade_py/devtools/design_quality/__init__.py": frozenset(
        {"DesignReport", "Finding", "Severity", "evaluate_change", "evaluate_changes"}
    ),
    "trade_py/devtools/openspec_status/__init__.py": frozenset({"collect_workflow"}),
}
_MAX_FILES = 2_048
_MAX_FILE_BYTES = 1 * 1024 * 1024
_MAX_TOTAL_BYTES = 32 * 1024 * 1024


def validate_target_architecture(repo_root: Path | str) -> tuple[ArchitectureFinding, ...]:
    """Return target-graph findings without importing target or legacy code."""

    root = Path(repo_root)
    kernel_root = root / "src" / "trade" / "kernel"
    if not kernel_root.is_dir():
        return ()

    findings: list[ArchitectureFinding] = []
    findings.extend(_validate_kernel_inventory(root, kernel_root))
    findings.extend(_validate_compat_inventory(root))
    sources, source_findings = _read_sources(root)
    findings.extend(source_findings)

    cli_reviewed = _reviewed_cli_inventory(sources)
    for source in sources:
        analysis = analyze_imports(source)
        findings.extend(_validate_edges(source, analysis.edges))
        findings.extend(_validate_dynamic_behavior(source, analysis, cli_reviewed))
        if source.module.startswith("trade.kernel"):
            findings.extend(_validate_kernel_vocabulary(source))
    return tuple(
        sorted(
            set(findings),
            key=lambda item: (item.path, item.line or 0, item.rule_id, item.message),
        )
    )


def _validate_kernel_inventory(root: Path, kernel_root: Path) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    for path in sorted(kernel_root.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        kernel_relative = path.relative_to(kernel_root).as_posix()
        if kernel_relative not in _KERNEL_FILES:
            findings.append(
                _finding(
                    KERNEL_MODULE_ALLOWLIST,
                    relative,
                    None,
                    f"{relative}:<module> violates trade.kernel -> exact six-module allowlist",
                    "Keep only ids, time, digest, errors, result and envelope modules.",
                )
            )
    return findings


def _validate_compat_inventory(root: Path) -> list[ArchitectureFinding]:
    compat_root = root / "trade_py" / "compat"
    if not compat_root.exists():
        return []
    findings: list[ArchitectureFinding] = []
    for path in sorted(compat_root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        compat_relative = path.relative_to(compat_root).as_posix()
        if compat_relative not in _COMPAT_FILES:
            findings.append(
                _finding(
                    COMPAT_AGGREGATE_REEXPORT,
                    relative,
                    None,
                    f"{relative}:<module> violates compat -> exact owner leaf adapters",
                    "Remove aggregate/cross-owner compatibility modules; retain only the four reviewed leaves.",
                )
            )
    return findings


def _read_sources(root: Path) -> tuple[list[PythonSource], list[ArchitectureFinding]]:
    sources: list[PythonSource] = []
    findings: list[ArchitectureFinding] = []
    total_bytes = 0
    paths: list[Path] = []
    for source_root in (root / "src" / "trade", root / "trade_py", root / "trade_web"):
        if source_root.is_dir():
            paths.extend(sorted(source_root.rglob("*.py")))
    if len(paths) > _MAX_FILES:
        return [], [
            _finding(
                TARGET_SOURCE_UNAVAILABLE,
                "src/trade",
                None,
                f"source inventory has {len(paths)} files; limit is {_MAX_FILES}",
                "Split or explicitly revise the reviewed target-guard source budget.",
            )
        ]
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            findings.append(
                _finding(
                    TARGET_SOURCE_UNAVAILABLE,
                    relative,
                    None,
                    f"{relative}:<module> cannot be audited because source is a symlink",
                    "Use a regular tracked Python source file.",
                )
            )
            continue
        try:
            payload = path.read_bytes()
        except OSError as error:
            findings.append(
                _finding(
                    TARGET_SOURCE_UNAVAILABLE,
                    relative,
                    None,
                    f"{relative}:<module> cannot be read: {type(error).__name__}",
                    "Restore a readable regular Python source file.",
                )
            )
            continue
        total_bytes += len(payload)
        if len(payload) > _MAX_FILE_BYTES or total_bytes > _MAX_TOTAL_BYTES:
            findings.append(
                _finding(
                    TARGET_SOURCE_UNAVAILABLE,
                    relative,
                    None,
                    f"{relative}:<module> exceeds the reviewed static-scan byte budget",
                    "Split the source or explicitly revise the reviewed target-guard budget.",
                )
            )
            continue
        try:
            text = payload.decode("utf-8")
            tree = ast.parse(text, filename=relative)
        except (SyntaxError, UnicodeError) as error:
            findings.append(
                _finding(
                    TARGET_SOURCE_UNAVAILABLE,
                    relative,
                    getattr(error, "lineno", None),
                    f"{relative}:<module> cannot be parsed: {type(error).__name__}",
                    "Restore valid UTF-8 Python source before architecture validation.",
                )
            )
            continue
        sources.append(
            PythonSource(
                relative_path=relative,
                module=module_name(relative),
                is_package=path.name == "__init__.py",
                tree=tree,
            )
        )
    return sources, findings


def _validate_edges(
    source: PythonSource,
    edges: tuple[ImportEdge, ...],
) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    for edge in edges:
        target = edge.target
        if is_stdlib(target):
            continue
        if source.module.startswith("trade.kernel"):
            if not matches_any(target, _KERNEL_PREFIXES) and target != "trade.kernel":
                findings.append(
                    _edge_finding(
                        KERNEL_DEPENDENCY,
                        source,
                        edge,
                        "trade.kernel -> standard library or admitted Kernel module",
                        "Move owner/framework behavior out of Kernel.",
                    )
                )
        elif source.module.startswith("trade.platform"):
            if matches_any(target, _LEGACY_PREFIXES):
                findings.append(
                    _edge_finding(
                        TARGET_LEGACY_DEPENDENCY,
                        source,
                        edge,
                        "trade.platform -> legacy package",
                        "Depend on Kernel or owner ports/contracts instead of legacy implementation.",
                    )
                )
            elif target.startswith("trade.processes") or not matches_any(
                target, ("trade.kernel", "trade.platform")
            ):
                findings.append(
                    _edge_finding(
                        PLATFORM_DEPENDENCY,
                        source,
                        edge,
                        "trade.platform -> trade.processes or non-public dependency",
                        "Keep Platform contracts dependent only on Kernel and their own package.",
                    )
                )
        elif source.module.startswith("trade.processes"):
            if matches_any(target, _LEGACY_PREFIXES):
                findings.append(
                    _edge_finding(
                        TARGET_LEGACY_DEPENDENCY,
                        source,
                        edge,
                        "trade.processes -> legacy package",
                        "Depend only on Kernel and Platform public contracts.",
                    )
                )
            elif not matches_any(
                target,
                ("trade.kernel", "trade.processes", "trade.platform.contracts"),
            ):
                findings.append(
                    _edge_finding(
                        PROCESSES_DEPENDENCY,
                        source,
                        edge,
                        "trade.processes -> dependency outside Kernel/Platform public contracts",
                        "Replace the edge with a Kernel or Platform public-contract dependency.",
                    )
                )
        elif source.module == "trade":
            findings.append(
                _edge_finding(
                    PLATFORM_DEPENDENCY,
                    source,
                    edge,
                    "trade package marker -> implementation re-export",
                    "Keep the package marker side-effect and aggregate-re-export free.",
                )
            )
        elif source.module in _COMPAT_MODULES:
            allowed = _COMPAT_ALLOWED_PREFIXES[source.module]
            if not matches_any(target, allowed):
                findings.append(
                    _edge_finding(
                        COMPAT_ADAPTER_BOUNDARY,
                        source,
                        edge,
                        f"{source.module} -> dependency outside its reviewed owner/targets",
                        "Import only the mapper's reviewed legacy owner and target contracts.",
                    )
                )
        elif source.module.startswith(("trade_py", "trade_web")):
            if matches_any(target, _TARGET_PREFIXES) or matches_any(target, tuple(_COMPAT_MODULES)):
                findings.append(
                    _edge_finding(
                        RUNTIME_ADOPTION_FENCE,
                        source,
                        edge,
                        "legacy production -> target contract or compatibility adapter",
                        "Keep target contracts test-only until the runtime-hardening child is approved.",
                    )
                )
    return findings


def _validate_dynamic_behavior(
    source: PythonSource,
    analysis: ImportAnalysis,
    cli_reviewed: bool,
) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    for issue in analysis.unresolved:
        if (
            source.relative_path == "trade_py/cli/main.py"
            and issue.importer_symbol == "<module>._import_domain"
            and issue.reviewed_cli_shape
            and cli_reviewed
        ):
            continue
        findings.append(
            _finding(
                DYNAMIC_IMPORT_UNRESOLVED,
                source.relative_path,
                issue.line,
                (
                    f"{source.relative_path}:{issue.importer_symbol} has unresolved import edge "
                    f"{issue.expression}"
                ),
                "Use a literal target or an exact reviewed finite legacy-only allowlist.",
            )
        )
    if analysis.module_getattr_line is not None:
        expected = _FINITE_GETATTR_EXPORTS.get(source.relative_path)
        actual = literal_all(source.tree)
        if expected is None or actual != expected:
            findings.append(
                _finding(
                    DYNAMIC_REEXPORT,
                    source.relative_path,
                    analysis.module_getattr_line,
                    (
                        f"{source.relative_path}:<module>.__getattr__ creates an unresolved "
                        "dynamic re-export edge"
                    ),
                    "Remove module __getattr__ or bind its exact finite legacy-only exports.",
                )
            )
    for issue in analysis.dynamic_reexports:
        findings.append(
            _finding(
                DYNAMIC_REEXPORT,
                source.relative_path,
                issue.line,
                (
                    f"{source.relative_path}:{issue.importer_symbol} creates dynamic re-export "
                    f"edge {issue.expression}"
                ),
                "Replace dynamic package mutation with explicit owner-local imports.",
            )
        )
    return findings


def _validate_kernel_vocabulary(source: PythonSource) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    for node in ast.walk(source.tree):
        values: list[str] = []
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            values.append(node.name)
        elif isinstance(node, ast.Name):
            values.append(node.id)
        elif isinstance(node, ast.Attribute):
            values.append(node.attr)
        elif isinstance(node, ast.arg):
            values.append(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
        for value in values:
            words = {word.lower() for word in _WORD_TOKEN.findall(value)}
            forbidden = sorted(words & _KERNEL_OWNER_WORDS)
            if forbidden:
                findings.append(
                    _finding(
                        KERNEL_OWNER_VOCABULARY,
                        source.relative_path,
                        getattr(node, "lineno", None),
                        (
                            f"{source.relative_path}:<module> introduces owner vocabulary "
                            f"{', '.join(forbidden)} into trade.kernel"
                        ),
                        "Move the owner-specific value or wording into its owning contracts.",
                    )
                )
    return findings


def _reviewed_cli_inventory(sources: list[PythonSource]) -> bool:
    source = next(
        (item for item in sources if item.relative_path == "trade_py/cli/main.py"),
        None,
    )
    if source is None:
        return False
    modules: set[str] = set()
    for node in ast.walk(source.tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id in {"canonical_domains", "legacy_domains"}
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return False
        for item in node.value.elts:
            if not isinstance(item, ast.Tuple) or len(item.elts) < 2:
                return False
            module = literal_string(item.elts[1])
            if module is None:
                return False
            modules.add(module)
    return modules == set(_CLI_MODULES)


def _edge_finding(
    rule_id: str,
    source: PythonSource,
    edge: ImportEdge,
    violated_edge: str,
    remediation: str,
) -> ArchitectureFinding:
    kind = "dynamic import" if edge.dynamic else "import"
    return _finding(
        rule_id,
        source.relative_path,
        edge.line,
        (
            f"{source.relative_path}:{edge.importer_symbol} {kind}s {edge.symbol}; "
            f"violated edge: {violated_edge}"
        ),
        remediation,
    )


def _finding(
    rule_id: str,
    path: str,
    line: int | None,
    message: str,
    remediation: str,
) -> ArchitectureFinding:
    return ArchitectureFinding(
        rule_id=rule_id,
        path=path,
        line=line,
        message=message,
        remediation=remediation,
    )


__all__ = [
    "COMPAT_ADAPTER_BOUNDARY",
    "COMPAT_AGGREGATE_REEXPORT",
    "DYNAMIC_IMPORT_UNRESOLVED",
    "DYNAMIC_REEXPORT",
    "KERNEL_DEPENDENCY",
    "KERNEL_MODULE_ALLOWLIST",
    "KERNEL_OWNER_VOCABULARY",
    "PLATFORM_DEPENDENCY",
    "PROCESSES_DEPENDENCY",
    "RUNTIME_ADOPTION_FENCE",
    "TARGET_LEGACY_DEPENDENCY",
    "TARGET_SOURCE_UNAVAILABLE",
    "validate_target_architecture",
]
