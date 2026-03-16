from __future__ import annotations


def infer_a_share_suffix(code: str) -> str:
    """Infer the canonical exchange suffix for a 6-digit A-share code."""
    normalized = str(code).strip().upper().split(".", 1)[0]
    if normalized.startswith("92"):
        return ".BJ"
    if normalized.startswith(("4", "8")):
        return ".BJ"
    if normalized.startswith(("6", "9")):
        return ".SH"
    return ".SZ"


def ensure_a_share_symbol(code_or_symbol: str) -> str:
    """Return a canonical A-share symbol, correcting legacy suffix mistakes."""
    value = str(code_or_symbol).strip().upper()
    if not value:
        return value
    if "." in value:
        code, suffix = value.split(".", 1)
        if code.isdigit() and len(code) == 6 and suffix in {"SH", "SZ", "BJ"}:
            return code + infer_a_share_suffix(code)
        return f"{code}.{suffix}"
    if value.isdigit() and len(value) == 6:
        return value + infer_a_share_suffix(value)
    return value
