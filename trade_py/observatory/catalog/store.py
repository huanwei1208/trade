"""Catalog persistence and generation management (WP1).

The Catalog projection is materialized to a standalone rebuildable SQLite database
at `<data_root>/market/crypto/observatory/catalog.sqlite`. It is additive and never
required for correctness (always rebuildable from immutable facts).

Generation switching uses an atomic pointer file with compare-and-swap semantics so
concurrent readers observe one complete generation. Read paths only verify the
source fingerprint and return `CATALOG_STALE` when the projection is behind the
immutable facts; they never write the projection.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from trade_py.observatory.catalog.projection import (
    Catalog,
    build_catalog,
    compute_source_fingerprint,
)
from trade_py.observatory.domain.vocab import (
    CATALOG_SCHEMA_VERSION,
    ObservatoryError,
    ReasonCode,
)


def _observatory_dir(data_root: str | Path) -> Path:
    return Path(data_root) / "market" / "crypto" / "observatory"


def _catalog_paths(data_root: str | Path) -> tuple[Path, Path]:
    base = _observatory_dir(data_root)
    return base / "catalog.sqlite", base / "generation.json"


def _crypto_paths(data_root: str | Path) -> tuple[Path, Path, Path]:
    crypto_root = Path(data_root) / "market" / "crypto"
    return (
        crypto_root / "runs" / "btc",
        crypto_root / "audit",
        crypto_root / "btc_current.json",
    )


def current_source_fingerprint(data_root: str | Path) -> str:
    runs_dir, audit_dir, current_path = _crypto_paths(data_root)
    return compute_source_fingerprint(runs_dir, audit_dir, current_path)


def _write_sqlite(catalog: Catalog, db_path: Path) -> None:
    """Materialize the projection to a fresh SQLite file (additive projection)."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY, created_at TEXT, market_watermark TEXT,
                data_readiness TEXT, canonical_rows INTEGER, canonical_hash TEXT,
                lifecycle_state TEXT, quality_state TEXT, acquisition_state TEXT,
                payload TEXT
            );
            CREATE TABLE releases (
                release_id TEXT PRIMARY KEY, run_id TEXT, published_at TEXT,
                previous_release_id TEXT, lifecycle_state TEXT, payload TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO catalog_meta VALUES (?,?)",
            ("catalog_schema_version", catalog.catalog_schema_version),
        )
        conn.execute(
            "INSERT INTO catalog_meta VALUES (?,?)",
            ("source_fingerprint", catalog.source_fingerprint),
        )
        conn.execute(
            "INSERT INTO catalog_meta VALUES (?,?)",
            ("generation_id", catalog.generation_id),
        )
        conn.execute(
            "INSERT INTO catalog_meta VALUES (?,?)",
            ("content_hash", catalog.content_hash()),
        )
        conn.execute(
            "INSERT INTO catalog_meta VALUES (?,?)",
            ("current_run_id", catalog.current_run_id or ""),
        )
        for run in catalog.runs.values():
            conn.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.created_at,
                    run.market_watermark,
                    run.data_readiness,
                    run.canonical_rows,
                    run.canonical_hash,
                    run.lifecycle_state.value,
                    run.quality_state.value,
                    run.acquisition_state.value,
                    json.dumps({"blocking_gate": run.blocking_gate}),
                ),
            )
        for rel in catalog.releases:
            conn.execute(
                "INSERT INTO releases VALUES (?,?,?,?,?,?)",
                (
                    rel.release_id,
                    rel.run_id,
                    rel.published_at,
                    rel.previous_release_id,
                    rel.lifecycle_state.value,
                    json.dumps({"audit_ref": rel.audit_ref}),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def rebuild(data_root: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Full rebuild. With dry_run, materialize to a temp DB and report only."""

    catalog = build_catalog(data_root)
    db_path, gen_path = _catalog_paths(data_root)
    report = {
        "action": "rebuild",
        "dry_run": dry_run,
        "catalog_schema_version": catalog.catalog_schema_version,
        "source_fingerprint": catalog.source_fingerprint,
        "generation_id": catalog.generation_id,
        "content_hash": catalog.content_hash(),
        "run_count": len(catalog.runs),
        "release_count": len(catalog.releases),
        "current_run_id": catalog.current_run_id,
    }
    if dry_run:
        # Dry-run materializes to the system temp dir, never inside the real data
        # root, so a dry-run on real data leaves data/ untouched.
        tmp_dir = Path(tempfile.mkdtemp(prefix="obs-catalog-dryrun-"))
        tmp_db = tmp_dir / "catalog.sqlite"
        _write_sqlite(catalog, tmp_db)
        report["dry_run_db"] = str(tmp_db)
        return report
    # Atomic generation switch: write new DB, then CAS the generation pointer.
    _write_sqlite(catalog, db_path)
    _cas_generation(gen_path, catalog)
    report["committed"] = True
    return report


def update(data_root: str | Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Incremental update. Result content hash must equal a full rebuild.

    The projection is small (order 10k rows), so update recomputes the projection
    from immutable facts (deterministic) rather than mutating in place. This keeps
    incremental == full by construction while still short-circuiting when the
    fingerprint is unchanged.
    """

    db_path, gen_path = _catalog_paths(data_root)
    live_fp = current_source_fingerprint(data_root)
    stored = load_generation(data_root)
    if stored and stored.get("source_fingerprint") == live_fp:
        return {"action": "update", "changed": False, "source_fingerprint": live_fp}
    report = rebuild(data_root, dry_run=dry_run)
    report["action"] = "update"
    report["changed"] = True
    return report


def _cas_generation(gen_path: Path, catalog: Catalog) -> None:
    payload = {
        "catalog_schema_version": catalog.catalog_schema_version,
        "source_fingerprint": catalog.source_fingerprint,
        "generation_id": catalog.generation_id,
        "content_hash": catalog.content_hash(),
    }
    gen_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(gen_path.parent), prefix=".gen-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
        os.replace(tmp, gen_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_generation(data_root: str | Path) -> dict[str, Any] | None:
    _, gen_path = _catalog_paths(data_root)
    if not gen_path.exists():
        return None
    try:
        return json.loads(gen_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verify(data_root: str | Path) -> dict[str, Any]:
    """Reconcile the stored generation against live immutable facts."""

    stored = load_generation(data_root)
    live_fp = current_source_fingerprint(data_root)
    if stored is None:
        return {"action": "verify", "status": "missing", "live_fingerprint": live_fp}
    stale = stored.get("source_fingerprint") != live_fp
    schema_mismatch = stored.get("catalog_schema_version") != CATALOG_SCHEMA_VERSION
    return {
        "action": "verify",
        "status": "stale" if (stale or schema_mismatch) else "current",
        "stored_fingerprint": stored.get("source_fingerprint"),
        "live_fingerprint": live_fp,
        "schema_mismatch": schema_mismatch,
    }


def status(data_root: str | Path) -> dict[str, Any]:
    stored = load_generation(data_root)
    db_path, _ = _catalog_paths(data_root)
    return {
        "action": "status",
        "db_exists": db_path.exists(),
        "generation": stored,
        "verify": verify(data_root),
    }


def load_catalog_checked(data_root: str | Path) -> Catalog:
    """Load the projection for a READ, failing closed if stale.

    Reads never rebuild. If the stored generation is missing or its source
    fingerprint no longer matches the immutable facts, this raises CATALOG_STALE.
    """

    stored = load_generation(data_root)
    live_fp = current_source_fingerprint(data_root)
    if stored is None:
        raise ObservatoryError(
            ReasonCode.CATALOG_STALE,
            "catalog projection is not built",
            retryable=True,
            extra={"retry_after": 1},
        )
    if stored.get("source_fingerprint") != live_fp:
        raise ObservatoryError(
            ReasonCode.CATALOG_STALE,
            "catalog projection is behind immutable facts",
            retryable=True,
            extra={"retry_after": 1},
        )
    if stored.get("catalog_schema_version") != CATALOG_SCHEMA_VERSION:
        raise ObservatoryError(
            ReasonCode.CATALOG_STALE,
            "catalog schema version mismatch",
            retryable=True,
        )
    # The projection matches the immutable facts; rebuild the in-memory view
    # deterministically (no write). This is a pure read of immutable facts.
    return build_catalog(data_root)
