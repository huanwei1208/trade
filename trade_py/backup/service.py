from __future__ import annotations

import hashlib
import json
import os
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trade_py.backup.gdrive import GoogleDriveBackupDriver, GoogleDriveConfig
from trade_py.db.trade_db import TradeDB


@dataclass(frozen=True)
class BackupConfig:
    backend: str
    enabled: bool
    google_drive_key_file: str
    google_drive_folder_id: str
    google_drive_timeout_ms: int
    google_drive_retry_count: int
    backup_remote_dir: str


def _bool_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _load_backup_config(data_root: str | Path) -> BackupConfig:
    db = TradeDB(data_root)
    return BackupConfig(
        backend=str(db.get("storage.backend", "local") or os.environ.get("TRADE_STORAGE_BACKEND", "local")).strip(),
        enabled=_bool_text(db.get("storage.enabled", "0") or os.environ.get("TRADE_STORAGE_ENABLED", "0")),
        google_drive_key_file=str(
            db.get("storage.google_drive_key_file", "")
            or os.environ.get("TRADE_GOOGLE_DRIVE_KEY_FILE", "")
        ).strip(),
        google_drive_folder_id=str(
            db.get("storage.google_drive_folder_id", "")
            or os.environ.get("TRADE_GOOGLE_DRIVE_FOLDER_ID", "")
        ).strip(),
        google_drive_timeout_ms=int(db.get("storage.google_drive_timeout_ms", 30000) or 30000),
        google_drive_retry_count=int(db.get("storage.google_drive_retry_count", 2) or 2),
        backup_remote_dir=str(
            db.get("storage.backup_remote_dir", "trade-backups")
            or os.environ.get("TRADE_BACKUP_REMOTE_DIR", "trade-backups")
        ).strip(),
    )


def _snapshot_id() -> str:
    return "snap_" + datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _backups_root(data_root: str | Path) -> Path:
    return Path(data_root) / "backups"


def _archive_dir(data_root: str | Path) -> Path:
    root = _backups_root(data_root) / "archives"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_dir(data_root: str | Path) -> Path:
    root = _backups_root(data_root) / "manifests"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _should_skip(path: Path, data_root: Path) -> bool:
    rel = path.relative_to(data_root).as_posix()
    if rel.startswith("backups/"):
        return True
    if any(part in {"__pycache__", ".ipynb_checkpoints"} for part in path.parts):
        return True
    if path.name.endswith((".lock", ".tmp")):
        return True
    return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _driver_from_config(config: BackupConfig) -> GoogleDriveBackupDriver:
    return GoogleDriveBackupDriver(
        GoogleDriveConfig(
            service_account_json_path=config.google_drive_key_file,
            root_folder_id=config.google_drive_folder_id,
            timeout_ms=config.google_drive_timeout_ms,
            retry_count=config.google_drive_retry_count,
        )
    )


def create_backup_snapshot(
    data_root: str | Path = "data",
    *,
    label: str = "",
) -> dict[str, Any]:
    data_path = Path(data_root)
    snapshot_id = _snapshot_id()
    archive_path = _archive_dir(data_root) / f"{snapshot_id}.tar.gz"
    manifest_path = _manifest_dir(data_root) / f"{snapshot_id}.json"
    file_entries: list[dict[str, Any]] = []

    with tarfile.open(archive_path, "w:gz") as tar:
        for path in sorted(data_path.rglob("*")):
            if not path.is_file():
                continue
            if _should_skip(path, data_path):
                continue
            rel = path.relative_to(data_path).as_posix()
            tar.add(path, arcname=rel)
            stat = path.stat()
            file_entries.append(
                {
                    "path": rel,
                    "size_bytes": int(stat.st_size),
                    "mtime": int(stat.st_mtime),
                }
            )

    manifest = {
        "snapshot_id": snapshot_id,
        "label": label,
        "data_root": str(data_path),
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive_name": archive_path.name,
        "file_count": len(file_entries),
        "size_bytes": int(archive_path.stat().st_size),
        "sha256": _sha256_file(archive_path),
        "files": file_entries,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    db = TradeDB(data_root)
    db.backup_snapshot_upsert(
        {
            "snapshot_id": snapshot_id,
            "label": label,
            "driver": "local",
            "scope": "data_root",
            "archive_path": str(archive_path),
            "manifest_path": str(manifest_path),
            "status": "created",
            "size_bytes": manifest["size_bytes"],
            "file_count": manifest["file_count"],
            "sha256": manifest["sha256"],
        }
    )
    return {
        "snapshot_id": snapshot_id,
        "archive_path": str(archive_path),
        "manifest_path": str(manifest_path),
        "size_bytes": manifest["size_bytes"],
        "file_count": manifest["file_count"],
        "sha256": manifest["sha256"],
    }


def list_backup_snapshots(data_root: str | Path = "data", *, limit: int = 20) -> list[dict[str, Any]]:
    return TradeDB(data_root).backup_snapshots_recent(limit=limit)


def push_backup_snapshot(
    data_root: str | Path = "data",
    *,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    db = TradeDB(data_root)
    row = db.backup_snapshot_get(snapshot_id) if snapshot_id else None
    if row is None:
        recent = db.backup_snapshots_recent(limit=1)
        row = recent[0] if recent else None
    if row is None:
        raise RuntimeError("no backup snapshot found")

    config = _load_backup_config(data_root)
    if config.backend != "google_drive":
        raise RuntimeError(f"storage backend is not google_drive: {config.backend}")
    driver = _driver_from_config(config)
    if not driver.available():
        raise RuntimeError("google drive backup driver not configured")

    snapshot_id = str(row["snapshot_id"])
    archive_path = Path(str(row["archive_path"] or ""))
    manifest_path = Path(str(row["manifest_path"] or ""))
    remote_dir = f"{config.backup_remote_dir}/{snapshot_id}"
    remote_archive_path = f"{remote_dir}/{archive_path.name}"
    remote_manifest_path = f"{remote_dir}/{manifest_path.name}"

    archive_info = driver.upload_file(archive_path, remote_archive_path)
    manifest_info = driver.upload_file(manifest_path, remote_manifest_path)
    db.backup_snapshot_upsert(
        {
            "snapshot_id": snapshot_id,
            "label": row.get("label"),
            "driver": "google_drive",
            "scope": row.get("scope") or "data_root",
            "archive_path": str(archive_path),
            "manifest_path": str(manifest_path),
            "remote_archive_path": archive_info["remote_path"],
            "remote_manifest_path": manifest_info["remote_path"],
            "status": "pushed",
            "size_bytes": int(row.get("size_bytes") or 0),
            "file_count": int(row.get("file_count") or 0),
            "sha256": row.get("sha256"),
        }
    )
    return {
        "snapshot_id": snapshot_id,
        "remote_archive_path": archive_info["remote_path"],
        "remote_manifest_path": manifest_info["remote_path"],
    }


def restore_backup_snapshot(
    data_root: str | Path = "data",
    *,
    snapshot_id: str,
    target_root: str | Path | None = None,
) -> dict[str, Any]:
    db = TradeDB(data_root)
    row = db.backup_snapshot_get(snapshot_id)
    if row is None:
        raise RuntimeError(f"snapshot not found: {snapshot_id}")
    archive_path = Path(str(row.get("archive_path") or ""))
    if not archive_path.exists():
        config = _load_backup_config(data_root)
        driver = _driver_from_config(config)
        remote_archive_path = str(row.get("remote_archive_path") or "")
        if not remote_archive_path:
            raise RuntimeError("snapshot archive missing locally and no remote path recorded")
        driver.download_file(remote_archive_path, archive_path)

    target = (
        Path(target_root)
        if target_root
        else Path(data_root).parent / f"{Path(data_root).name}.restore" / snapshot_id
    )
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(target)
    db.backup_snapshot_upsert(
        {
            "snapshot_id": snapshot_id,
            "label": row.get("label"),
            "driver": row.get("driver") or "local",
            "scope": row.get("scope") or "data_root",
            "archive_path": str(archive_path),
            "manifest_path": row.get("manifest_path"),
            "remote_archive_path": row.get("remote_archive_path"),
            "remote_manifest_path": row.get("remote_manifest_path"),
            "status": "restored",
            "size_bytes": int(row.get("size_bytes") or 0),
            "file_count": int(row.get("file_count") or 0),
            "sha256": row.get("sha256"),
            "restored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    return {"snapshot_id": snapshot_id, "target_root": str(target), "archive_path": str(archive_path)}


def backup_doctor(data_root: str | Path = "data") -> dict[str, Any]:
    config = _load_backup_config(data_root)
    driver = _driver_from_config(config)
    return {
        "backend": config.backend,
        "enabled": config.enabled,
        "google_drive_key_file": config.google_drive_key_file,
        "google_drive_folder_id": config.google_drive_folder_id,
        "google_drive_available": driver.available(),
        "backup_remote_dir": config.backup_remote_dir,
    }
