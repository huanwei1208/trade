"""Unified CLI entrypoints for trade_py."""
from __future__ import annotations

import argparse


def epilog_from_subparsers(parser: argparse.ArgumentParser) -> str:
    """Build a help epilog by collecting description + epilog from every subparser."""
    subparsers_action = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)),
        None,
    )
    if not subparsers_action:
        return ""

    choices = subparsers_action.choices
    # De-duplicate aliases (argparse adds alias → same parser object)
    seen: set[int] = set()
    unique: list[tuple[str, argparse.ArgumentParser]] = []
    for name, sub in choices.items():
        if id(sub) not in seen:
            seen.add(id(sub))
            unique.append((name, sub))

    width = max((len(n) for n, _ in unique), default=8)

    desc_lines = ["子命令:"]
    example_lines: list[str] = []

    for name, sub in unique:
        desc_lines.append(f"  {name:<{width}}  {sub.description or ''}")
        if sub.epilog:
            for line in sub.epilog.strip().splitlines():
                example_lines.append(f"  {line}")

    result = "\n".join(desc_lines)
    if example_lines:
        result += "\n\n示例:\n" + "\n".join(example_lines)
    return result
