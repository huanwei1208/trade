"""HTML stripping and text normalization."""

from __future__ import annotations

import re


def clean_html(text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
