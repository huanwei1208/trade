from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


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
