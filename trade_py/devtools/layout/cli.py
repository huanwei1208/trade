"""Machine-readable entry point for the package authority guard."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from trade_py.devtools.layout.authority import validate_authority_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trade-layout-authority")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--candidate", action="append", default=[])
    args = parser.parse_args(argv)

    report = validate_authority_manifest(
        Path(args.repo_root),
        candidate_paths=tuple(args.candidate),
    )
    payload = {
        "schema_version": "trade.layout.authority-report.v1",
        "status": "PASS" if report.ok else "FAIL",
        "exit_code": report.exit_code,
        "index": (
            {
                "scanner_name": report.tree_index.scanner_name,
                "scanner_version": report.tree_index.scanner_version,
                "scanner_source_digest": report.tree_index.scanner_source_digest,
                "rules_digest": report.tree_index.rules_digest,
                "tree_digest": report.tree_index.tree_digest,
                "source_count": len(report.tree_index.entries),
                "source_bytes": report.tree_index.source_bytes,
            }
            if report.tree_index is not None
            else None
        ),
        "authorities": [asdict(item) for item in report.authorities],
        "findings": [asdict(item) for item in report.findings],
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
