"""Immutable, conversation-scoped scene artifacts, locally or in private Blob Storage."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)

MAX_SCENE_BYTES = 1024 * 1024


class RenderManifest(TypedDict):
    version: int
    id: str
    instant: str
    createdAt: str
    sign: str
    degrees: float
    longitude: float
    latitude: float
    solarConstellation: str
    timeAssumption: str
    dataSize: int
    dataEtag: str


def state_directory() -> Path:
    default = (
        Path.home() / ".aistro"
        if os.environ.get("ARTIFACT_STORAGE") == "blob"
        else Path(__file__).parent / ".aistro"
    )
    return Path(os.environ.get("AISTRO_STATE_DIR", default))


def artifact_prefix(scope: str, render_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", scope) or not re.fullmatch(r"[a-f0-9]{32}", render_id):
        raise ValueError("Invalid conversation scope or render identifier.")
    return f"zodiac/{scope}/{render_id}"


class RenderStore:
    def __init__(self) -> None:
        self.mode = os.environ.get("ARTIFACT_STORAGE", "local")
        if self.mode not in {"local", "blob"}:
            raise ValueError("ARTIFACT_STORAGE must be local or blob.")
        self.account = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "")
        self.container = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "aistro")
        self.credential: DefaultAzureCredential | None = None
        self.service: BlobServiceClient | None = None
        if self.mode == "blob":
            if not re.fullmatch(r"[a-z0-9]{3,24}", self.account):
                raise ValueError("Configure AZURE_STORAGE_ACCOUNT_NAME for Blob artifacts.")
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", self.container):
                raise ValueError("Invalid AZURE_STORAGE_CONTAINER_NAME.")
            self.credential = DefaultAzureCredential()
            self.service = BlobServiceClient(self.storage_origin, credential=self.credential)

    def _require_private(self) -> None:
        if self.service is None:
            raise ValueError("This operation requires Blob artifact storage.")
        properties = self.service.get_container_client(self.container).get_container_properties()
        if properties.get("public_access"):
            raise ValueError("The artifact container must be private.")

    @property
    def storage_origin(self) -> str:
        return f"https://{self.account}.blob.core.windows.net"

    def close(self) -> None:
        if self.service is not None:
            self.service.close()
        if self.credential is not None:
            self.credential.close()

    def save(
        self,
        scope: str,
        manifest: RenderManifest,
        data: dict,
        html: str,
        source: str,
    ) -> None:
        prefix = artifact_prefix(scope, manifest["id"])
        payload = json.dumps(data, ensure_ascii=True, allow_nan=False).encode()
        if len(payload) > MAX_SCENE_BYTES:
            raise ValueError("The astronomical scene exceeds 1 MiB.")
        manifest["dataSize"] = len(payload)
        files = {
            "data.json": (payload, "application/json"),
            "chart.html": (html.encode(), "text/html; charset=utf-8"),
            "source.txt": (source.encode(), "text/plain; charset=utf-8"),
        }
        if self.service is None:
            directory = state_directory() / "artifacts" / prefix
            directory.mkdir(parents=True, exist_ok=False)
            for name, (content, _) in files.items():
                (directory / name).write_bytes(content)
            # The manifest is the commit marker: readers never list partial renders.
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            return
        self._require_private()
        for name, (content, media_type) in files.items():
            result = self.service.get_blob_client(self.container, f"{prefix}/{name}").upload_blob(
                content,
                overwrite=False,
                content_settings=ContentSettings(content_type=media_type, cache_control="no-store"),
            )
            if name == "data.json":
                manifest["dataEtag"] = result["etag"]
        self.service.get_blob_client(self.container, f"{prefix}/manifest.json").upload_blob(
            json.dumps(manifest),
            overwrite=False,
            content_settings=ContentSettings(
                content_type="application/json", cache_control="no-store"
            ),
        )

    def signed_snapshot(self, scope: str, render_id: str) -> dict:
        if self.service is None:
            raise ValueError("Teams widgets require private Blob artifact storage.")
        self._require_private()
        prefix = artifact_prefix(scope, render_id)
        manifest_blob = self.service.get_blob_client(self.container, f"{prefix}/manifest.json")
        if manifest_blob.get_blob_properties().size > 16 * 1024:
            raise ValueError("Invalid artifact manifest.")
        manifest = json.loads(manifest_blob.download_blob().readall())
        blob = self.service.get_blob_client(self.container, f"{prefix}/data.json")
        properties = blob.get_blob_properties()
        if (
            manifest.get("id") != render_id
            or manifest.get("version") != 1
            or not 0 < properties.size <= MAX_SCENE_BYTES
            or manifest.get("dataSize") != properties.size
            or manifest.get("dataEtag") != properties.etag
        ):
            raise ValueError("This astronomical snapshot has changed or is unavailable.")
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=15)
        key = self.service.get_user_delegation_key(now - timedelta(minutes=5), expires)
        token = generate_blob_sas(
            account_name=self.account,
            container_name=self.container,
            blob_name=f"{prefix}/data.json",
            user_delegation_key=key,
            permission=BlobSasPermissions(read=True),
            start=now - timedelta(minutes=5),
            expiry=expires,
            protocol="https",
        )
        return {
            "version": 1,
            "id": render_id,
            "size": properties.size,
            "url": f"{blob.url}?{token}",
            "expiresAt": expires.isoformat(),
        }
