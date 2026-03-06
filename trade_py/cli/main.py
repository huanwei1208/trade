from __future__ import annotations

import argparse

from trade_py.cli import account, data, model, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trade")
    parser.add_argument("domain", choices=["data", "model", "report", "account"])
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.domain == "data":
        return data.main(args.args)
    if args.domain == "model":
        return model.main(args.args)
    if args.domain == "report":
        return report.main(args.args)
    if args.domain == "account":
        return account.main(args.args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
