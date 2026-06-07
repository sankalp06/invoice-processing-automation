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
    ContentSettings,
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

        self._service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        self._account_name = settings.storage_account_name
        self._account_key = settings.storage_account_key
        self._sas_expiry_hours = settings.sas_expiry_hours

    # ------------------------------------------------------------------
    # Backward compatibility methods
    # ------------------------------------------------------------------

    def container(self, container_name: str):
        """
        Backward-compatible method expected by older workflows.
        Returns Azure SDK ContainerClient.
        """
        return self._service_client.get_container_client(container_name)

    def download_bytes(self, container: str, blob_name: str) -> bytes:
        """
        Backward-compatible alias.
        """
        return self.download_blob_bytes(container, blob_name)

    def upload_file(
        self,
        container: str,
        blob_name: str,
        file_path: str,
        overwrite: bool = True,
    ) -> None:
        """
        Backward-compatible file uploader expected by older workflows.
        """
        with open(file_path, "rb") as f:
            self.upload_blob(
                container=container,
                blob_name=blob_name,
                data=f,
                content_type="application/pdf",
                overwrite=overwrite,
            )

    # ------------------------------------------------------------------
    # SAS generation
    # ------------------------------------------------------------------

    def get_blob_sas_url(
        self,
        container: str,
        blob_name: str,
        read: bool = True,
        write: bool = False,
        create: bool = False,
    ) -> str:
        token = generate_blob_sas(
            account_name=self._account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=self._account_key,
            permission=BlobSasPermissions(
                read=read,
                write=write,
                create=create,
            ),
            expiry=datetime.now(UTC)
            + timedelta(hours=self._sas_expiry_hours),
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
            expiry=datetime.now(UTC)
            + timedelta(hours=self._sas_expiry_hours),
        )

        return (
            f"https://{self._account_name}.blob.core.windows.net/"
            f"{container}?{token}"
        )

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_blobs(self, container: str) -> Iterator[str]:
        container_client = self._service_client.get_container_client(container)

        for blob in container_client.list_blobs():
            yield blob.name

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_blob_bytes(
        self,
        container: str,
        blob_name: str,
    ) -> bytes:
        logger.debug("Downloading blob %s/%s", container, blob_name)

        blob_client = self._service_client.get_blob_client(
            container=container,
            blob=blob_name,
        )

        return blob_client.download_blob().readall()

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_blob(
        self,
        container: str,
        blob_name: str,
        data,
        content_type: str = "application/octet-stream",
        overwrite: bool = True,
    ) -> None:
        logger.debug(
            "Uploading to %s/%s (%s)",
            container,
            blob_name,
            content_type,
        )

        blob_client: BlobClient = self._service_client.get_blob_client(
            container=container,
            blob=blob_name,
        )

        blob_client.upload_blob(
            data,
            overwrite=overwrite,
            content_settings=ContentSettings(
                content_type=content_type
            ),
        )

    # ------------------------------------------------------------------
    # Existence check
    # ------------------------------------------------------------------

    def blob_exists(
        self,
        container: str,
        blob_name: str,
    ) -> bool:
        blob_client = self._service_client.get_blob_client(
            container=container,
            blob=blob_name,
        )

        return blob_client.exists()