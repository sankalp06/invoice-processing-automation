"""
src/clients/blob_client.py
───────────────────────────
Thin, testable wrapper around azure-storage-blob.
Handles SAS generation, listing, downloading, and uploading.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Iterator

from azure.storage.blob import (
    BlobClient,
    BlobSasPermissions,
    BlobServiceClient,
    ContainerSasPermissions,
    generate_blob_sas,
    generate_container_sas,
)

from config.settings import settings

logger = logging.getLogger(__name__)


class AzureBlobStorageClient:
    """Encapsulates all Azure Blob Storage operations for the pipeline."""

    def __init__(self) -> None:
        connection_string = (
            f"DefaultEndpointsProtocol=https;"
            f"AccountName={settings.storage_account_name};"
            f"AccountKey={settings.storage_account_key};"
            f"EndpointSuffix=core.windows.net"
        )
        self._service_client = BlobServiceClient.from_connection_string(connection_string)
        self._account_name = settings.storage_account_name
        self._account_key = settings.storage_account_key
        self._sas_expiry_hours = settings.sas_expiry_hours

    # ── SAS generation ─────────────────────────────────────────────────────

    def get_blob_sas_url(
        self,
        container: str,
        blob_name: str,
        read: bool = True,
        write: bool = False,
        create: bool = False,
    ) -> str:
        """Generate a time-limited SAS URL for a single blob."""
        token = generate_blob_sas(
            account_name=self._account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=self._account_key,
            permission=BlobSasPermissions(read=read, write=write, create=create),
            expiry=datetime.now(UTC) + timedelta(hours=self._sas_expiry_hours),
        )
        return (
            f"https://{self._account_name}.blob.core.windows.net/"
            f"{container}/{blob_name}?{token}"
        )

    def get_container_sas_url(
        self,
        container: str,
        read: bool = True,
        write: bool = False,
        create: bool = False,
        list_blobs: bool = True,
    ) -> str:
        """Generate a time-limited SAS URL for an entire container."""
        token = generate_container_sas(
            account_name=self._account_name,
            container_name=container,
            account_key=self._account_key,
            permission=ContainerSasPermissions(
                read=read,
                write=write,
                create=create,
                list=list_blobs,
            ),
            expiry=datetime.now(UTC) + timedelta(hours=self._sas_expiry_hours),
        )
        return (
            f"https://{self._account_name}.blob.core.windows.net/{container}?{token}"
        )

    # ── Listing ────────────────────────────────────────────────────────────

    def list_blobs(self, container: str) -> Iterator[str]:
        """Yield the name of every blob in *container*."""
        container_client = self._service_client.get_container_client(container)
        for blob in container_client.list_blobs():
            yield blob.name

    # ── Download ───────────────────────────────────────────────────────────

    def download_blob_bytes(self, container: str, blob_name: str) -> bytes:
        """Download a blob and return its raw bytes."""
        logger.debug("Downloading blob %s/%s", container, blob_name)
        blob_client = self._service_client.get_blob_client(
            container=container, blob=blob_name
        )
        return blob_client.download_blob().readall()

    # ── Upload ─────────────────────────────────────────────────────────────

    def upload_blob(
        self,
        container: str,
        blob_name: str,
        data: bytes | str,
        content_type: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> None:
        """Upload *data* to *container*/*blob_name*."""
        logger.debug("Uploading to %s/%s (%s)", container, blob_name, content_type)
        blob_client: BlobClient = self._service_client.get_blob_client(
            container=container, blob=blob_name
        )
        blob_client.upload_blob(
            data,
            overwrite=overwrite,
            content_settings=self._content_settings(content_type),
        )

    @staticmethod
    def _content_settings(content_type: str):
        from azure.storage.blob import ContentSettings

        return ContentSettings(content_type=content_type)

    def blob_exists(self, container: str, blob_name: str) -> bool:
        """Return True if the blob already exists."""
        blob_client = self._service_client.get_blob_client(
            container=container, blob=blob_name
        )
        return blob_client.exists()
