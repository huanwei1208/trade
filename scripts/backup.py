"""Backup service — combined GoogleDrive driver + snapshot logic.

Moved from trade_py/backup/ to scripts/ for clearer separation from
the core trade_py domain package.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from trade_py.db.trade_db import TradeDB


# ── Google Drive driver ────────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class GoogleDriveConfig:
    service_account_json_path: str
    root_folder_id: str
    timeout_ms: int = 30000
    retry_count: int = 2


class GoogleDriveBackupDriver:
    def __init__(self, config: GoogleDriveConfig) -> None:
        self._config = config
        self._token: str = ""
        self._token_expiry: float = 0.0
        self._folder_cache: dict[str, str] = {}

        self._client_email = ""
        self._private_key_pem = ""
        key_file = str(config.service_account_json_path or "").strip()
        if not key_file:
            return
        path = Path(key_file)
        if not path.exists() or path.is_dir():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self._client_email = str(payload.get("client_email") or "")
        self._private_key_pem = str(payload.get("private_key") or "")

    def available(self) -> bool:
        return bool(self._client_email and self._private_key_pem and self._config.root_folder_id)

    def _sign(self, signing_input: str) -> bytes:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fp:
            fp.write(self._private_key_pem)
            key_path = fp.name
        try:
            proc = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", key_path, "-binary"],
                input=signing_input.encode("utf-8"),
                capture_output=True,
                check=True,
            )
            return proc.stdout
        finally:
            try:
                os.unlink(key_path)
            except OSError:
                pass

    def _create_jwt(self) -> str:
        now = int(time.time())
        header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
        payload = _b64url(
            json.dumps(
                {
                    "iss": self._client_email,
                    "scope": "https://www.googleapis.com/auth/drive",
                    "aud": "https://oauth2.googleapis.com/token",
                    "exp": now + 3600,
                    "iat": now,
                },
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signing_input = f"{header}.{payload}"
        signature = _b64url(self._sign(signing_input))
        return f"{signing_input}.{signature}"

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry:
            return self._token
        if not self.available():
            return ""
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._create_jwt(),
            },
            timeout=max(5.0, self._config.timeout_ms / 1000.0),
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = str(payload.get("access_token") or "")
        self._token_expiry = time.time() + int(payload.get("expires_in") or 3500) - 30
        return self._token

    def _auth_headers(self, *, content_type: str | None = None) -> dict[str, str]:
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        timeout = max(5.0, self._config.timeout_ms / 1000.0)
        last_exc: Exception | None = None
        for _ in range(max(1, self._config.retry_count + 1)):
            try:
                resp = requests.request(method, url, timeout=timeout, **kwargs)
                resp.raise_for_status()
                return resp
            except Exception as exc:
                last_exc = exc
                time.sleep(1.0)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("google drive request failed")

    def _find_in_folder(self, parent_id: str, name: str) -> str:
        escaped = name.replace("'", "\\'")
        q = f"name = '{escaped}' and '{parent_id}' in parents and trashed=false"
        url = (
            "https://www.googleapis.com/drive/v3/files"
            f"?q={quote(q)}&fields=files(id,name)&pageSize=1"
        )
        resp = self._request("GET", url, headers=self._auth_headers())
        payload = resp.json()
        files = payload.get("files") or []
        if not files:
            return ""
        return str(files[0].get("id") or "")

    def _create_folder(self, parent_id: str, name: str) -> str:
        resp = self._request(
            "POST",
            "https://www.googleapis.com/drive/v3/files?fields=id",
            headers=self._auth_headers(content_type="application/json"),
            data=json.dumps(
                {
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                }
            ),
        )
        return str(resp.json().get("id") or "")

    def _resolve_dir(self, remote_rel_dir: str) -> str:
        rel = str(remote_rel_dir or "").strip().strip("/")
        if not rel:
            return self._config.root_folder_id
        if rel in self._folder_cache:
            return self._folder_cache[rel]
        parent_id = self._config.root_folder_id
        current = []
        for part in rel.split("/"):
            if not part:
                continue
            current.append(part)
            current_rel = "/".join(current)
            cached = self._folder_cache.get(current_rel)
            if cached:
                parent_id = cached
                continue
            folder_id = self._find_in_folder(parent_id, part)
            if not folder_id:
                folder_id = self._create_folder(parent_id, part)
            if not folder_id:
                raise RuntimeError(f"failed to resolve folder {current_rel}")
            self._folder_cache[current_rel] = folder_id
            parent_id = folder_id
        return parent_id

    def upload_file(self, local_path: str | Path, remote_rel_path: str) -> dict[str, str]:
        path = Path(local_path)
        parent_rel = str(Path(remote_rel_path).parent).replace("\\", "/")
        name = Path(remote_rel_path).name
        parent_id = self._resolve_dir("" if parent_rel == "." else parent_rel)
        existing_id = self._find_in_folder(parent_id, name)
        metadata = {"name": name}
        if not existing_id:
            metadata["parents"] = [parent_id]
        init_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id"
        method = "POST"
        if existing_id:
            init_url = f"https://www.googleapis.com/upload/drive/v3/files/{existing_id}?uploadType=resumable&fields=id"
            method = "PATCH"
        init_resp = self._request(
            method,
            init_url,
            headers={
                **self._auth_headers(content_type="application/json; charset=UTF-8"),
                "X-Upload-Content-Type": "application/gzip",
            },
            data=json.dumps(metadata),
        )
        upload_url = init_resp.headers.get("Location")
        if not upload_url:
            raise RuntimeError("missing resumable upload location")
        with path.open("rb") as fp:
            resp = self._request(
                "PUT",
                upload_url,
                headers={
                    "Authorization": self._auth_headers()["Authorization"],
                    "Content-Type": "application/gzip",
                },
                data=fp,
            )
        payload = resp.json()
        return {"file_id": str(payload.get("id") or existing_id or ""), "remote_path": remote_rel_path}

    def download_file(self, remote_rel_path: str, local_path: str | Path) -> str:
        remote = Path(remote_rel_path)
        parent_id = self._resolve_dir("" if str(remote.parent) == "." else str(remote.parent).replace("\\", "/"))
        file_id = self._find_in_folder(parent_id, remote.name)
        if not file_id:
            raise FileNotFoundError(remote_rel_path)
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        resp = self._request("GET", url, headers=self._auth_headers(), stream=True)
        out = Path(local_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("wb") as fp:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fp.write(chunk)
        return str(out)

    def list_files(self, remote_rel_dir: str) -> list[str]:
        dir_id = self._resolve_dir(remote_rel_dir)
        q = f"'{dir_id}' in parents and trashed=false"
        url = (
            "https://www.googleapis.com/drive/v3/files"
            f"?q={quote(q)}&fields=nextPageToken,files(name)&pageSize=1000"
        )
        resp = self._request("GET", url, headers=self._auth_headers())
        payload = resp.json()
        return [str(item.get("name") or "") for item in payload.get("files") or []]


# ── Backup service ────────────────────────────────────────────────────────────

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


__all__ = [
    "backup_doctor",
    "create_backup_snapshot",
    "list_backup_snapshots",
    "push_backup_snapshot",
    "restore_backup_snapshot",
]
