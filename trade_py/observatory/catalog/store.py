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


# The generation-identity fields that the pointer file (generation.json) and the
# materialized SQLite `catalog_meta` MUST both carry and agree on. Any missing,
# wrong-type, or mismatched value makes the projection corrupt (fail closed).
_GENERATION_KEYS = (
    "catalog_schema_version",
    "source_fingerprint",
    "generation_id",
    "content_hash",
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
    """Best-effort read of the generation pointer as a mapping.

    Returns the parsed dict, or ``None`` when the pointer is absent, unreadable,
    not valid JSON, or valid JSON that is not an object. Returning ``None`` for a
    non-dict pointer keeps every downstream ``.get()`` caller (update/verify/status
    /load_catalog_checked) traceback-free; the richer corrupt/incomplete
    classification lives in :func:`read_generation` / :func:`capability`.
    """

    _, gen_path = _catalog_paths(data_root)
    if not gen_path.exists():
        return None
    try:
        parsed = json.loads(gen_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def read_generation(data_root: str | Path) -> tuple[str, dict[str, Any] | None]:
    """Classify the generation pointer file as a total, fail-closed parser.

    Returns ``(status, payload)`` where ``status`` is one of:
      - ``"absent"``: the pointer file does not exist.
      - ``"malformed"``: the file exists but is not readable JSON, is not a JSON
        object, or carries a required identity field of the wrong type.
      - ``"incomplete"``: a well-formed JSON object that is missing one or more of
        the required identity fields (``catalog_schema_version``,
        ``source_fingerprint``, ``generation_id``, ``content_hash``).
      - ``"ok"``: a well-formed object with all required identity fields present as
        non-empty strings.

    ``payload`` is the parsed object for ``incomplete``/``ok`` (and for
    ``malformed`` when the file parsed to a dict but a field had the wrong type),
    otherwise ``None``. This never raises for corrupt/partial pointers — callers
    downstream treat every non-``ok`` status as ``catalog_corrupt`` rather than
    tracebacking.
    """

    _, gen_path = _catalog_paths(data_root)
    if not gen_path.exists():
        return "absent", None
    try:
        raw = gen_path.read_text(encoding="utf-8")
    except OSError:
        return "malformed", None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return "malformed", None
    if not isinstance(parsed, dict):
        # A JSON scalar/array is a structurally wrong pointer, not a partial one.
        return "malformed", None
    missing = [key for key in _GENERATION_KEYS if key not in parsed]
    # Any present identity field must be a non-empty string; a wrong-type value
    # (int/list/None) is a corrupt pointer, not merely an incomplete one.
    for key in _GENERATION_KEYS:
        if key in parsed and not (isinstance(parsed[key], str) and parsed[key]):
            return "malformed", parsed
    if missing:
        return "incomplete", parsed
    return "ok", parsed


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


def _read_sqlite_meta(db_path: Path) -> dict[str, str] | None:
    """Read-only structural probe of the materialized SQLite projection.

    Opens the file in ``mode=ro`` (never creating or writing it), runs
    ``PRAGMA integrity_check``, requires the ``catalog_meta``/``runs``/``releases``
    tables to exist, and returns the ``catalog_meta`` key/value map. Returns
    ``None`` when the file does not exist, is not a valid SQLite database, fails
    the integrity check, or is missing a required table — i.e. every structural
    failure maps to ``None`` (the caller treats that as ``catalog_corrupt``).
    """

    if not db_path.exists():
        return None
    try:
        # uri=True + mode=ro guarantees SQLite never creates or mutates the file.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            return None
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not {"catalog_meta", "runs", "releases"} <= names:
            return None
        meta = {
            str(key): str(value)
            for key, value in conn.execute(
                "SELECT key, value FROM catalog_meta"
            ).fetchall()
        }
    except sqlite3.DatabaseError:
        # Corrupt/truncated file that sqlite could open the header of but not read.
        return None
    finally:
        conn.close()
    return meta


def capability(data_root: str | Path) -> dict[str, Any]:
    """Read-only Catalog readiness classification for rollout gating (RA.1).

    A total, fail-closed classifier that inspects the generation pointer and the
    materialized SQLite projection and returns exactly one of ``catalog_missing``,
    ``catalog_stale``, ``catalog_corrupt``, or ``ready``. It NEVER builds, migrates,
    or writes the projection (safe to call from startup and GET paths) and NEVER
    raises for a partial/corrupt install — every defect is classified, not
    tracebacked. ``disabled`` is owned by the Web layer feature flag, not here.

    Classification order (all fail closed):
      1. No pointer AND no DB           -> ``catalog_missing``
      2. Pointer present but not ``ok`` -> ``catalog_corrupt`` (malformed/wrong-type
         /incomplete pointer, even if a DB exists)
      3. Pointer ``ok`` but DB missing  -> ``catalog_corrupt`` (a committed pointer
         with no projection is inconsistent, never "missing")
      4. SQLite fails integrity/tables  -> ``catalog_corrupt``
      5. SQLite ``catalog_meta`` differs from the pointer on any identity field
         (``catalog_schema_version``/``source_fingerprint``/``generation_id``/
         ``content_hash``) -> ``catalog_corrupt``
      6. Projection is behind the live immutable facts -> ``catalog_stale``
      7. Otherwise -> ``ready``
    """

    db_path, _ = _catalog_paths(data_root)
    gen_status, stored = read_generation(data_root)
    db_exists = db_path.exists()

    if gen_status == "absent" and not db_exists:
        return {"state": "catalog_missing", "db_exists": False, "generation_id": None}

    def _gen_id() -> str | None:
        if isinstance(stored, dict):
            value = stored.get("generation_id")
            return value if isinstance(value, str) and value else None
        return None

    if gen_status == "absent":
        # DB present but no pointer: a projection with no committed generation is
        # inconsistent, not merely missing. Fail closed as corrupt.
        return {"state": "catalog_corrupt", "db_exists": True, "generation_id": None}
    if gen_status != "ok":
        # Malformed / wrong-type / incomplete pointer -> corrupt (never traceback).
        return {"state": "catalog_corrupt", "db_exists": db_exists, "generation_id": _gen_id()}
    if not db_exists:
        # A complete pointer that references a projection which is not on disk.
        return {"state": "catalog_corrupt", "db_exists": False, "generation_id": _gen_id()}

    meta = _read_sqlite_meta(db_path)
    if meta is None:
        return {"state": "catalog_corrupt", "db_exists": True, "generation_id": _gen_id()}

    # The SQLite projection must describe the SAME generation the pointer commits
    # to. Any identity-field disagreement means the two artifacts drifted (e.g. a
    # half-finished CAS or a hand-edited pointer) and the read side must fail closed
    # rather than trust a DB whose generation_id/content_hash the pointer disowns.
    for key in _GENERATION_KEYS:
        if meta.get(key) != stored.get(key):
            return {
                "state": "catalog_corrupt",
                "db_exists": True,
                "generation_id": _gen_id(),
                "meta_mismatch": key,
            }

    verification = verify(data_root)
    state = "ready" if verification["status"] == "current" else "catalog_stale"
    return {
        "state": state,
        "db_exists": True,
        "generation_id": _gen_id(),
        "verify_status": verification["status"],
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
