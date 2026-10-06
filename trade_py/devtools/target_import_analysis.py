"""Bounded AST import facts for the target architecture guard."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PythonSource:
    relative_path: str
    module: str
    is_package: bool
    tree: ast.Module


@dataclass(frozen=True, slots=True)
class ImportEdge:
    target: str
    symbol: str
    line: int
    importer_symbol: str
    dynamic: bool = False


@dataclass(frozen=True, slots=True)
class DynamicIssue:
    line: int
    importer_symbol: str
    expression: str
    reviewed_cli_shape: bool = False


@dataclass(frozen=True, slots=True)
class ImportAnalysis:
    edges: tuple[ImportEdge, ...]
    unresolved: tuple[DynamicIssue, ...]
    module_getattr_line: int | None
    dynamic_reexports: tuple[DynamicIssue, ...]


class _ImportCollector(ast.NodeVisitor):
    def __init__(self, source: PythonSource) -> None:
        self._source = source
        self._scope = ["<module>"]
        self.edges: list[ImportEdge] = []
        self.unresolved: list[DynamicIssue] = []
        self.module_getattr_line: int | None = None
        self.dynamic_reexports: list[DynamicIssue] = []
        self._importlib_aliases = {"importlib"}
        self._import_call_names = {"__import__"}

    @property
    def _symbol(self) -> str:
        return ".".join(self._scope)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.edges.append(
                ImportEdge(
                    target=alias.name,
                    symbol=alias.name,
                    line=node.lineno,
                    importer_symbol=self._symbol,
                )
            )
            if alias.name == "importlib":
                self._importlib_aliases.add(alias.asname or alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = resolve_from_base(self._source, node)
        for alias in node.names:
            symbol = f"{base}.{alias.name}" if base else alias.name
            target = base if alias.name == "*" else symbol
            self.edges.append(
                ImportEdge(
                    target=target,
                    symbol=symbol,
                    line=node.lineno,
                    importer_symbol=self._symbol,
                )
            )
            if base == "importlib" and alias.name == "import_module":
                self._import_call_names.add(alias.asname or alias.name)
            if base == "builtins" and alias.name == "__import__":
                self._import_call_names.add(alias.asname or alias.name)

    def visit_Assign(self, node: ast.Assign) -> None:
        if _is_import_callable(node.value, self._importlib_aliases, self._import_call_names):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._import_call_names.add(target.id)
        if self._symbol == "<module>" and _is_dynamic_export_target(node.targets):
            self.dynamic_reexports.append(
                DynamicIssue(node.lineno, self._symbol, _expression(node))
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and _is_import_callable(
            node.value, self._importlib_aliases, self._import_call_names
        ):
            if isinstance(node.target, ast.Name):
                self._import_call_names.add(node.target.id)
        if self._symbol == "<module>" and _is_dynamic_export_target((node.target,)):
            self.dynamic_reexports.append(
                DynamicIssue(node.lineno, self._symbol, _expression(node))
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_import_callable(node.func, self._importlib_aliases, self._import_call_names):
            target = literal_string(node.args[0]) if node.args else None
            if target is None:
                self.unresolved.append(
                    DynamicIssue(
                        node.lineno,
                        self._symbol,
                        _expression(node),
                        reviewed_cli_shape=_is_reviewed_cli_dynamic_import(
                            self._source, self._symbol, node
                        ),
                    )
                )
            else:
                self.edges.append(
                    ImportEdge(
                        target=target,
                        symbol=target,
                        line=node.lineno,
                        importer_symbol=self._symbol,
                        dynamic=True,
                    )
                )
        if self._symbol == "<module>" and _is_dynamic_export_call(node):
            self.dynamic_reexports.append(
                DynamicIssue(node.lineno, self._symbol, _expression(node))
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self._symbol == "<module>" and node.name == "__getattr__":
            self.module_getattr_line = node.lineno
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if self._symbol == "<module>" and node.name == "__getattr__":
            self.module_getattr_line = node.lineno
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()


def analyze_imports(source: PythonSource) -> ImportAnalysis:
    collector = _ImportCollector(source)
    collector.visit(source.tree)
    return ImportAnalysis(
        edges=tuple(collector.edges),
        unresolved=tuple(collector.unresolved),
        module_getattr_line=collector.module_getattr_line,
        dynamic_reexports=tuple(collector.dynamic_reexports),
    )


def resolve_from_base(source: PythonSource, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = source.module.split(".") if source.is_package else source.module.split(".")[:-1]
    keep = len(package) - (node.level - 1)
    base = package[: max(keep, 0)]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def module_name(relative_path: str) -> str:
    path = relative_path.removesuffix(".py")
    if path.endswith("/__init__"):
        path = path[: -len("/__init__")]
    if path.startswith("src/"):
        path = path[len("src/") :]
    return path.replace("/", ".")


def literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = literal_string(node.left)
        right = literal_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        values: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            values.append(value.value)
        return "".join(values)
    return None


def literal_all(tree: ast.Module) -> frozenset[str] | None:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return None
        names = {literal_string(item) for item in value.elts}
        return frozenset(name for name in names if name is not None) if None not in names else None
    return None


def is_stdlib(target: str) -> bool:
    top_level = target.split(".", 1)[0]
    return top_level == "__future__" or top_level in sys.stdlib_module_names


def matches_any(target: str, prefixes: tuple[str, ...]) -> bool:
    return any(target == prefix or target.startswith(prefix + ".") for prefix in prefixes)


def _is_reviewed_cli_dynamic_import(
    source: PythonSource,
    symbol: str,
    node: ast.Call,
) -> bool:
    if source.relative_path != "trade_py/cli/main.py" or symbol != "<module>._import_domain":
        return False
    if len(node.args) != 1 or node.keywords:
        return False
    expression = node.args[0]
    if not isinstance(expression, ast.JoinedStr) or len(expression.values) != 2:
        return False
    prefix, variable = expression.values
    return (
        isinstance(prefix, ast.Constant)
        and prefix.value == "trade_py.cli."
        and isinstance(variable, ast.FormattedValue)
        and isinstance(variable.value, ast.Name)
        and variable.value.id == "name"
    )


def _is_import_callable(
    node: ast.AST,
    importlib_aliases: set[str],
    import_call_names: set[str],
) -> bool:
    if isinstance(node, ast.Name):
        return node.id in import_call_names
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id in importlib_aliases and node.attr == "import_module"
    if isinstance(node, ast.Call) and len(node.args) >= 2:
        return (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in importlib_aliases
            and literal_string(node.args[1]) == "import_module"
        )
    return False


def _is_dynamic_export_target(targets: tuple[ast.expr, ...] | list[ast.expr]) -> bool:
    for target in targets:
        if not isinstance(target, ast.Subscript):
            continue
        value = target.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id in {"globals", "locals"}:
                return True
    return False


def _is_dynamic_export_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call):
        owner = func.value.func
        return (
            isinstance(owner, ast.Name)
            and owner.id in {"globals", "locals"}
            and func.attr in {"update", "__setitem__"}
        )
    return (
        isinstance(func, ast.Name)
        and func.id == "setattr"
        and len(node.args) >= 2
        and (not isinstance(node.args[1], ast.Constant) or not isinstance(node.args[1].value, str))
    )


def _expression(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=False, include_attributes=False)[:240]


__all__ = [
    "DynamicIssue",
    "ImportAnalysis",
    "ImportEdge",
    "PythonSource",
    "analyze_imports",
    "is_stdlib",
    "literal_all",
    "literal_string",
    "matches_any",
    "module_name",
    "resolve_from_base",
]
