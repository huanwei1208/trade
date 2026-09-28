"""AST-based dependency and compatibility-forwarder validation."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import PurePosixPath

from trade_py.devtools.layout.models import AuthorityFinding, ImportEdge

_DYNAMIC_LOADER_NAMES = frozenset(
    {
        "__import__",
        "find_spec",
        "import_module",
    }
)
_OPTIONAL_IMPORT_TOKENS = frozenset(
    {
        "fastmcp",
        "mcp",
        "pluggy",
        "plugin",
        "plugins",
        "remote_worker",
        "remote_workers",
    }
)
_LOWER_LAYER_SEGMENTS = frozenset({"compat", "contracts", "domain", "use_cases"})


def import_edges(module: str, path: str, tree: ast.Module) -> list[ImportEdge]:
    edges: list[ImportEdge] = []
    aliases = _dynamic_loader_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            edges.extend(
                ImportEdge(module, imported, path, node.lineno)
                for imported in imported_names(node, consumer=module, path=path)
            )
        elif isinstance(node, ast.Call):
            resolved = (
                *_dynamic_import_names(node, aliases),
                *_mapped_dynamic_import_names(node, aliases),
            )
            edges.extend(ImportEdge(module, imported, path, node.lineno) for imported in resolved)
    return edges


def module_escape_findings(
    module: str,
    path: str,
    tree: ast.Module,
) -> list[AuthorityFinding]:
    if not is_target_module(module):
        return []
    findings: list[AuthorityFinding] = []
    lower_layer = any(part in _LOWER_LAYER_SEGMENTS for part in module.split("."))
    aliases = _dynamic_loader_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in imported_names(node, consumer=module, path=path):
                if name == "trade_py" or name.startswith("trade_py."):
                    findings.append(
                        AuthorityFinding(
                            "layout.authority.reverse_dependency",
                            path,
                            node.lineno,
                            f"target module imports legacy implementation {name}",
                        )
                    )
                if lower_layer and any(
                    token in name.split(".") for token in _OPTIONAL_IMPORT_TOKENS
                ):
                    findings.append(
                        AuthorityFinding(
                            "layout.authority.optional_dependency_leak",
                            path,
                            node.lineno,
                            f"lower layer imports optional interface dependency {name}",
                        )
                    )
        if isinstance(node, ast.Call):
            dynamic_names = (
                *_dynamic_import_names(node, aliases),
                *_mapped_dynamic_import_names(node, aliases),
            )
            dynamic_call = _is_dynamic_loader_call(node, aliases) or _is_mapped_loader_call(
                node, aliases
            )
            if lower_layer and dynamic_call and not dynamic_names:
                findings.append(
                    AuthorityFinding(
                        "layout.authority.dynamic_import_unresolved",
                        path,
                        node.lineno,
                        "lower layer uses a dynamic import whose module name is not static",
                    )
                )
            for name in dynamic_names:
                if name == "trade_py" or name.startswith("trade_py."):
                    findings.append(
                        AuthorityFinding(
                            "layout.authority.reverse_dependency",
                            path,
                            node.lineno,
                            f"target module dynamically imports legacy implementation {name}",
                        )
                    )
                if lower_layer and any(
                    token in name.split(".") for token in _OPTIONAL_IMPORT_TOKENS
                ):
                    findings.append(
                        AuthorityFinding(
                            "layout.authority.optional_dependency_leak",
                            path,
                            node.lineno,
                            f"lower layer dynamically imports optional dependency {name}",
                        )
                    )
        if isinstance(node, ast.Assign):
            if any(_is_sys_modules_subscript(target) for target in node.targets):
                findings.append(
                    AuthorityFinding(
                        "layout.authority.sys_modules_alias",
                        path,
                        node.lineno,
                        "target module installs a broad sys.modules alias",
                    )
                )
            if any(_is_dunder_path(target) for target in node.targets):
                findings.append(
                    AuthorityFinding(
                        "layout.authority.path_extension",
                        path,
                        node.lineno,
                        "target module assigns package __path__",
                    )
                )
        if isinstance(node, ast.AugAssign) and _is_dunder_path(node.target):
            findings.append(
                AuthorityFinding(
                    "layout.authority.path_extension",
                    path,
                    node.lineno,
                    "target module extends package __path__",
                )
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "extend", "insert"}
            and _is_dunder_path(node.func.value)
        ):
            findings.append(
                AuthorityFinding(
                    "layout.authority.path_extension",
                    path,
                    node.lineno,
                    "target module mutates package __path__",
                )
            )
        if isinstance(node, ast.Call) and _is_sys_modules_mutator(node.func):
            findings.append(
                AuthorityFinding(
                    "layout.authority.sys_modules_alias",
                    path,
                    node.lineno,
                    "target module mutates sys.modules through a broad helper",
                )
            )
        if isinstance(node, ast.Call) and _is_path_extension_call(node):
            findings.append(
                AuthorityFinding(
                    "layout.authority.path_extension",
                    path,
                    node.lineno,
                    "target module extends package search paths through a helper",
                )
            )
    return findings


def forwarder_optional_dependency_findings(
    module: str,
    path: str,
    tree: ast.Module,
    *,
    target_module: str,
) -> list[AuthorityFinding]:
    findings: list[AuthorityFinding] = []
    aliases = _dynamic_loader_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names: Iterable[str] = imported_names(node, consumer=module, path=path)
        elif isinstance(node, ast.Call) and (
            _is_dynamic_loader_call(node, aliases) or _is_mapped_loader_call(node, aliases)
        ):
            names = (
                *_dynamic_import_names(node, aliases),
                *_mapped_dynamic_import_names(node, aliases),
            )
            if not names:
                findings.append(
                    AuthorityFinding(
                        "layout.authority.dynamic_import_unresolved",
                        path,
                        node.lineno,
                        "compatibility forwarder uses a non-static dynamic import",
                    )
                )
        else:
            continue
        for name in names:
            if imports_module(name, target_module):
                continue
            if any(token in name.split(".") for token in _OPTIONAL_IMPORT_TOKENS):
                findings.append(
                    AuthorityFinding(
                        "layout.authority.optional_dependency_leak",
                        path,
                        node.lineno,
                        f"compatibility forwarder imports optional interface dependency {name}",
                    )
                )
    return findings


def imported_names(
    node: ast.Import | ast.ImportFrom,
    *,
    consumer: str | None = None,
    path: str | None = None,
) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if node.level:
        if consumer is None or path is None:
            return ()
        package = (
            consumer
            if PurePosixPath(path).name.startswith("__init__.")
            else consumer.rpartition(".")[0]
        )
        package_parts = package.split(".") if package else []
        parent_count = node.level - 1
        if parent_count > len(package_parts):
            return ()
        prefix = ".".join(package_parts[: len(package_parts) - parent_count])
        base = ".".join(part for part in (prefix, node.module or "") if part)
        return tuple(
            base if alias.name == "*" or not base else f"{base}.{alias.name}"
            for alias in node.names
        )
    base = node.module or ""
    return tuple(
        base if alias.name == "*" or not base else f"{base}.{alias.name}" for alias in node.names
    )


def is_thin_forwarder(tree: ast.Module, target_module: str) -> bool:
    delegates = False
    for statement in tree.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue
        if isinstance(statement, ast.ImportFrom) and statement.level == 0:
            if statement.module != target_module:
                return False
            delegates = True
            continue
        if isinstance(statement, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id == "__all__" for target in statement.targets
        ):
            continue
        return False
    return delegates


def is_inert_foundation(tree: ast.Module) -> bool:
    return all(
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
        for statement in tree.body
    )


def module_name(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix not in {".py", ".pyi"}:
        return None
    if pure.parts[:2] == ("src", "trade"):
        parts = ("trade", *pure.parts[2:])
    elif pure.parts and pure.parts[0] == "trade_py":
        parts = pure.parts
    else:
        return None
    if parts[-1] in {"__init__.py", "__init__.pyi"}:
        parts = parts[:-1]
    else:
        parts = (*parts[:-1], PurePosixPath(parts[-1]).stem)
    return ".".join(parts)


def imports_module(imported: str, selected: str) -> bool:
    return imported == selected or imported.startswith(f"{selected}.")


def _dynamic_loader_aliases(tree: ast.Module) -> frozenset[str]:
    aliases = {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"importlib", "importlib.util"}:
                    name = alias.asname or alias.name.partition(".")[0]
                    aliases.add(name)
        elif isinstance(node, ast.ImportFrom) and node.module in {
            "importlib",
            "importlib.util",
        }:
            for alias in node.names:
                if alias.name in _DYNAMIC_LOADER_NAMES:
                    aliases.add(alias.asname or alias.name)
                elif node.module == "importlib" and alias.name == "util":
                    aliases.add(alias.asname or alias.name)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if value is None or not _is_dynamic_loader_expr(value, frozenset(aliases)):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    changed = True
    return frozenset(aliases)


def _is_dynamic_loader_call(node: ast.Call, aliases: frozenset[str]) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id in aliases
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in _DYNAMIC_LOADER_NAMES:
        return False
    if isinstance(node.func.value, ast.Name):
        return node.func.value.id in aliases
    return (
        isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id in aliases
        and node.func.value.attr == "util"
    )


def _is_dynamic_loader_expr(node: ast.expr, aliases: frozenset[str]) -> bool:
    return _is_dynamic_loader_call(ast.Call(func=node, args=[], keywords=[]), aliases)


def _is_mapped_loader_call(node: ast.Call, aliases: frozenset[str]) -> bool:
    return (
        len(node.args) >= 2
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "map"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "map"
        )
        and _is_dynamic_loader_expr(node.args[0], aliases)
    )


def _dynamic_import_names(node: ast.Call, aliases: frozenset[str]) -> tuple[str, ...]:
    if not _is_dynamic_loader_call(node, aliases) or not node.args:
        return ()
    return _literal_names(node.args[0])


def _mapped_dynamic_import_names(
    node: ast.Call,
    aliases: frozenset[str],
) -> tuple[str, ...]:
    if not _is_mapped_loader_call(node, aliases):
        return ()
    return _literal_names(node.args[1])


def _literal_names(value: ast.expr) -> tuple[str, ...]:
    if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
        return (value.value,)
    if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        return ()
    names: list[str] = []
    for item in value.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str) or not item.value:
            return ()
        names.append(item.value)
    return tuple(names)


def is_target_module(module: str) -> bool:
    return module == "trade" or module.startswith("trade.")


def _is_sys_modules_subscript(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "modules"
    )


def _is_sys_modules_mutator(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in {"setdefault", "update"}
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "sys"
        and node.value.attr == "modules"
    )


def _is_dunder_path(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "__path__"


def _is_path_extension_call(node: ast.Call) -> bool:
    if not (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in {"extend_path", "declare_namespace"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"pkg_resources", "pkgutil"}
    ):
        return False
    return any(_is_dunder_path(argument) for argument in node.args)


__all__ = [
    "forwarder_optional_dependency_findings",
    "import_edges",
    "imports_module",
    "is_inert_foundation",
    "is_target_module",
    "is_thin_forwarder",
    "module_escape_findings",
    "module_name",
]
