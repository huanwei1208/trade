from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Locate trade_cli relative to project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_TRADE_CLI = _PROJECT_ROOT / "build" / "default" / "bin" / "trade_cli"
_CONFIG_PATH = str(_PROJECT_ROOT / "config")


def _run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run trade_cli with the given args. Returns (returncode, stdout, stderr)."""
    cmd = [str(_TRADE_CLI)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT),
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        logger.error("trade_cli not found at %s", _TRADE_CLI)
        return -1, "", f"trade_cli binary not found: {_TRADE_CLI}"
    except subprocess.TimeoutExpired:
        logger.error("trade_cli timed out after %ds", timeout)
        return -1, "", f"Command timed out after {timeout}s"


def cli_available() -> bool:
    """Return True if the trade_cli binary exists and is executable."""
    return _TRADE_CLI.exists() and _TRADE_CLI.is_file()


def get_features(symbol: str, scale: str = "zscore") -> dict[str, Any]:
    """Run `trade_cli features --symbol SYMBOL` and parse JSON output."""
    rc, out, err = _run([
        "features",
        "--config", _CONFIG_PATH,
        "--symbol", symbol,
        "--scale", scale,
    ], timeout=60)
    if rc != 0:
        logger.warning("features command failed (rc=%d): %s", rc, err)
        return {"error": err or "non-zero exit", "rc": rc}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # Return raw text if not JSON
        return {"raw": out.strip()}


def get_risk(symbol: str) -> dict[str, Any]:
    """Run `trade_cli risk --symbol SYMBOL` and parse JSON output."""
    rc, out, err = _run([
        "risk",
        "--config", _CONFIG_PATH,
        "--symbol", symbol,
    ], timeout=30)
    if rc != 0:
        logger.warning("risk command failed (rc=%d): %s", rc, err)
        return {"error": err or "non-zero exit", "rc": rc}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out.strip()}


def get_predict(symbol: str, model: str = "lgbm") -> dict[str, Any]:
    """Run `trade_cli predict --symbol SYMBOL --model MODEL`."""
    rc, out, err = _run([
        "predict",
        "--config", _CONFIG_PATH,
        "--symbol", symbol,
        "--model", model,
    ], timeout=60)
    if rc != 0:
        logger.warning("predict command failed (rc=%d): %s", rc, err)
        return {"error": err or "non-zero exit", "rc": rc}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out.strip()}


def run_backtest(
    symbol: str,
    start: str,
    end: str,
    strategy: str = "default",
) -> dict[str, Any]:
    """Run `trade_cli backtest`."""
    rc, out, err = _run([
        "backtest",
        "--config", _CONFIG_PATH,
        "--symbol", symbol,
        "--start", start,
        "--end", end,
        "--strategy", strategy,
    ], timeout=120)
    if rc != 0:
        return {"error": err or "non-zero exit", "rc": rc}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"raw": out.strip()}
