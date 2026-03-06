"""Arrow schema definition for Bronze sentiment records."""

from __future__ import annotations


def bronze_arrow_schema():
    """Return pyarrow schema when pyarrow is available, else None."""
    try:
        import pyarrow as pa
    except Exception:
        return None

    return pa.schema(
        [
            pa.field("source", pa.string()),
            pa.field("url", pa.string()),
            pa.field("title", pa.string()),
            pa.field("text", pa.string()),
            pa.field("published_at", pa.string()),
            pa.field("content_hash", pa.string()),
        ]
    )
