"""trade research — combined research/ML/evaluation domain.

Absorbs the former ``model``, ``factor``, and ``evaluate`` top-level domains.
All old commands are preserved via shims; this module is the new canonical entry.

Usage:
  trade research model <cmd> [args...]      # model training / list / compare / promote / predict / score
  trade research factor <cmd> [args...]     # factor status / evaluate / ic
  trade research evaluate <cmd> [args...]   # daily / source / event / model / gate evaluation
"""
from __future__ import annotations

import argparse
import sys

from trade_py.cli import global_flag_parent


_GROUPS = {
    "model": {
        "desc": "模型训练/推理/对比/上线/窗口得分/情绪IC/NLP训练",
        "examples": (
            "trade research model score\n"
            "trade research model build-features\n"
            "trade research model train\n"
            "trade research model list\n"
            "trade research model compare\n"
            "trade research model promote --model-id 12\n"
            "trade research model predict --symbol 600000.SH --event-type policy_easing\n"
            "trade research model sentiment-ic\n"
            "trade research model nlp-train\n"
            "trade research model sync-factors\n"
            "trade research model sync-signals\n"
            "trade research model build-labels"
        ),
    },
    "factor": {
        "desc": "因子仓与因子评估",
        "examples": (
            "trade research factor status\n"
            "trade research factor evaluate\n"
            "trade research factor ic --type graph --top 10"
        ),
    },
    "evaluate": {
        "desc": "评估层与质量门禁",
        "examples": (
            "trade research evaluate daily\n"
            "trade research evaluate source\n"
            "trade research evaluate event\n"
            "trade research evaluate model\n"
            "trade research evaluate gate"
        ),
    },
}


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade research",
        description="研究/建模/评估 — model + factor + evaluate 统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
        epilog=(
            "分组:\n"
            + "".join(f"  {k:<10}  {v['desc']}\n" for k, v in _GROUPS.items())
            + "\n示例:\n"
            + "".join(f"  {ex}\n" for v in _GROUPS.values() for ex in v["examples"].split("\n")[:2])
        ),
    )
    parser.add_argument("group", choices=list(_GROUPS.keys()), metavar="<group>",
                        help="{" + " | ".join(_GROUPS.keys()) + "}")
    parser.add_argument("rest", nargs=argparse.REMAINDER, metavar="...", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv or [])
    rest = list(args.rest)
    # argparse.REMAINDER may include a leading '--' separator; strip it.
    if rest and rest[0] == "--":
        rest = rest[1:]

    if args.group == "model":
        from trade_py.cli import model as model_cli
        return model_cli.main(
            rest,
            deprecated=False,
            prog="trade research model",
        )

    if args.group == "factor":
        from trade_py.cli import factor as factor_cli
        return factor_cli.main(
            rest,
            deprecated=False,
            prog="trade research factor",
        )

    if args.group == "evaluate":
        from trade_py.cli import evaluate as eval_cli
        return eval_cli.main(
            rest,
            deprecated=False,
            prog="trade research evaluate",
        )

    return 1
