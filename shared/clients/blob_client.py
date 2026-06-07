"""
shared/clients/blob_client.py
──────────────────────────────
Azure Blob Storage client using storage account name + access key.
All workflows share this single client — no SAS tokens required.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from azure.storage.blob import (
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
    BlobSasPermissions,
)

from config.settings import settings

logger = logging.getLogger(__name__)

_CONTENT_TYPES: dict[str, str] = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".json": "application/json",
    ".xml":  "application/xml",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
}


def _guess_content_type(blob_name: str) -> str:
    from pathlib import PurePosixPath
    return _CONTENT_TYPES.get(PurePosixPath(blob_name).suffix.lower(), "application/octet-stream")

class BlobStorageClient:
    """
    Wrapper around azure-storage-blob authenticated with account key.
    """

    def __init__(
        self,
        account_name: str | None = None,
        account_key: str | None = None,
    ) -> None:
        name = account_name or settings.storage_account_name
        key = account_key or settings.storage_account_key

        self._service = BlobServiceClient(
            account_url=f"https://{name}.blob.core.windows.net",
            credential=key,
        )
        self._account_name = name
        self._account_key = key

    # ── Container client ────────────────────────────────────────────────────

    def container(self, name: str):
        return self._service.get_container_client(name)

    def blob_client(self, container: str, blob_name: str):
        return self._service.get_blob_client(
            container=container,
            blob=blob_name,
        )

    # ── List ────────────────────────────────────────────────────────────────

    def list_blobs(self, container: str):
        return self._service.get_container_client(container).list_blobs()

    # ── Download ────────────────────────────────────────────────────────────

    def download_bytes(
        self,
        container: str,
        blob_name: str,
    ) -> bytes:
        logger.debug("Downloading %s / %s", container, blob_name)

        return (
            self._service
            .get_blob_client(
                container=container,
                blob=blob_name,
            )
            .download_blob()
            .readall()
        )

    # Backward compatibility
    def download_blob_bytes(
        self,
        container: str,
        blob_name: str,
    ) -> bytes:
        return self.download_bytes(container, blob_name)

    # ── Upload ──────────────────────────────────────────────────────────────

    def upload(
        self,
        container: str,
        blob_name: str,
        data: bytes | str,
        content_type: str | None = None,
        overwrite: bool = True,
    ) -> None:
        ct = content_type or _guess_content_type(blob_name)

        logger.debug(
            "Uploading %s / %s (%s)",
            container,
            blob_name,
            ct,
        )

        (
            self._service
            .get_blob_client(
                container=container,
                blob=blob_name,
            )
            .upload_blob(
                data,
                overwrite=overwrite,
                content_settings=ContentSettings(
                    content_type=ct
                ),
            )
        )

    # Backward compatibility
    def upload_blob(
        self,
        container: str,
        blob_name: str,
        data: bytes | str,
        content_type: str | None = None,
        overwrite: bool = True,
    ) -> None:
        self.upload(
            container=container,
            blob_name=blob_name,
            data=data,
            content_type=content_type,
            overwrite=overwrite,
        )

    def upload_file(
        self,
        container: str,
        blob_name: str,
        file_path: str,
        overwrite: bool = True,
    ) -> None:
        ct = _guess_content_type(blob_name)

        with open(file_path, "rb") as fh:
            self.upload(
                container,
                blob_name,
                fh.read(),
                content_type=ct,
                overwrite=overwrite,
            )

        logger.info(
            "Uploaded %s → %s / %s",
            file_path,
            container,
            blob_name,
        )

    # ── Existence check ────────────────────────────────────────────────────

    def exists(
        self,
        container: str,
        blob_name: str,
    ) -> bool:
        return (
            self._service
            .get_blob_client(
                container=container,
                blob=blob_name,
            )
            .exists()
        )

    # Backward compatibility
    def blob_exists(
        self,
        container: str,
        blob_name: str,
    ) -> bool:
        return self.exists(container, blob_name)

    # ── SAS URL ─────────────────────────────────────────────────────────────

    def get_blob_sas_url(
        self,
        container: str,
        blob_name: str,
        expiry_hours: int | None = None,
        read: bool = True,
    ) -> str:
        expiry = datetime.now(UTC) + timedelta(
            hours=expiry_hours or settings.sas_expiry_hours
        )

        token = generate_blob_sas(
            account_name=self._account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=self._account_key,
            permission=BlobSasPermissions(
                read=read,
            ),
            expiry=expiry,
        )

        return (
            f"https://{self._account_name}.blob.core.windows.net/"
            f"{container}/{blob_name}?{token}"
        )
# Alias for backward compatibility with existing workflows
AzureBlobStorageClient = BlobStorageClient
